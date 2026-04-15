#!/usr/bin/env python3
"""
Passerelle / Serveur IoT - Mini Projet 2026
=============================================
Rôles :
  1. Lire les données capteurs du micro:bit (passerelle RF) via port série (UART).
  2. Stocker ces données dans un fichier texte local.
  3. Servir les données à une application Android via UDP.
  4. Retransmettre les configurations d'affichage au micro:bit.


Architecture des threads :
  - Thread principal   : serveur UDP (bloque sur recvfrom)
  - Thread SerialReader: lecture continue du port série


Protocole UDP (port 10000) :
  Android → Serveur :
    "getValues()"   → répond avec la dernière mesure en JSON
    "getHistory()"  → répond avec les 10 dernières mesures en JSON
    "register"      → inscrit le client pour recevoir les données en temps réel (push)
    "unregister"    → désinscrit le client du push
    "TLH" / "HTP"  → envoie l'ordre d'affichage au micro:bit (lettres parmi T L H P)


  Serveur → Android :
    JSON de la mesure courante (en réponse à getValues ou en push lors d'une nouvelle mesure)


Format de données capteurs (reçu depuis le micro:bit via UART) :
  Exemple brut    : "T:24.5,L:312,H:58,P:1012"
  Exemple JSON    : {"T": 24.5, "L": 312, "H": 58, "P": 1012}
  Les deux formats sont acceptés automatiquement.


Légende des capteurs :
  T = Température (°C)
  L = Luminosité  (lux)
  H = Humidité    (%)
  P = Pression    (hPa)
"""


import socket
import threading
import time
import json
import os
import sys
from collections import deque
from datetime import datetime


try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False
    print("[AVERTISSEMENT] pyserial non installé. Lancez : pip install pyserial")
    print("[AVERTISSEMENT] Le serveur démarre en mode simulation (sans micro:bit).\n")




# ============================================================
# CONFIGURATION  — modifiez ces valeurs selon votre setup
# ============================================================


UDP_IP       = ""        # "" = écoute sur toutes les interfaces réseau
UDP_PORT     = 10000     # Port UDP d'écoute (par défaut selon le projet)


# Port série du micro:bit.
# Windows : "COM3", "COM4", ...  — vérifiez dans le Gestionnaire de périphériques
# Linux   : "/dev/ttyACM0" ou "/dev/ttyUSB0"
SERIAL_PORT  = "COM3"
SERIAL_BAUD  = 115200    # Vitesse UART — doit correspondre au code micro:bit


DATA_FILE    = "donnees_capteurs.txt"   # Fichier de stockage des mesures


# Ensemble des lettres capteurs valides pour les configs d'affichage
VALID_SENSORS = {'T', 'L', 'H', 'P'}




# ============================================================
# ÉTAT GLOBAL PARTAGÉ (protégé par des verrous)
# ============================================================


latest_data  = {}                      # Dernière mesure reçue
all_data     = deque(maxlen=1000)      # Historique en mémoire (max 1000 entrées)
data_lock    = threading.Lock()


android_clients = set()   # Adresses UDP des clients Android inscrits au push
clients_lock    = threading.Lock()




# ============================================================
# UTILITAIRES SÉRIE
# ============================================================


def _find_microbit_port():
    """Parcourt les ports série disponibles et renvoie celui du micro:bit, ou None."""
    if not SERIAL_AVAILABLE:
        return None
    for port in serial.tools.list_ports.comports():
        desc = port.description.lower()
        if "mbed" in desc or "microbit" in desc or "micro:bit" in desc:
            return port.device
    return None




def open_serial():
    """
    Tente d'ouvrir la connexion série avec le micro:bit.
    Cherche d'abord automatiquement le port, puis utilise SERIAL_PORT par défaut.
    Retourne l'objet Serial ou None si la connexion échoue (mode simulation).
    """
    if not SERIAL_AVAILABLE:
        return None


    port = _find_microbit_port() or SERIAL_PORT
    try:
        ser = serial.Serial(port, SERIAL_BAUD, timeout=1)
        print(f"[SÉRIE]  Connecté au micro:bit sur {port} à {SERIAL_BAUD} baud")
        return ser
    except serial.SerialException as e:
        print(f"[SÉRIE]  Impossible d'ouvrir {port} : {e}")
        print("[SÉRIE]  Démarrage en mode simulation (sans micro:bit)\n")
        return None




def send_to_microbit(ser, message: str) -> bool:
    """
    Envoie un message texte au micro:bit via UART.
    Le micro:bit doit lire une ligne complète (terminée par \\n).
    Retourne True si l'envoi a réussi.
    """
    if ser is None:
        print(f"[SÉRIE]  (simulation) → micro:bit : {message!r}")
        return True   # En simulation on considère l'envoi réussi


    try:
        ser.write((message.strip() + '\n').encode('utf-8'))
        print(f"[SÉRIE]  → micro:bit : {message!r}")
        return True
    except Exception as e:
        print(f"[SÉRIE]  Erreur d'envoi : {e}")
        return False




# ============================================================
# GESTION DES DONNÉES
# ============================================================


def parse_sensor_line(raw: str) -> dict:
    """
    Transforme une ligne brute reçue du micro:bit en dictionnaire Python.


    Deux formats acceptés :
      - Clé:valeur  →  "T:24.5,L:312,H:58,P:1012"
      - JSON        →  '{"T": 24.5, "L": 312}'


    Retourne toujours un dict avec au minimum "timestamp" et "raw".
    """
    entry = {
        "timestamp": datetime.now().isoformat(),
        "raw": raw,
    }


    # Essai JSON en premier
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            entry.update(parsed)
            return entry
    except (json.JSONDecodeError, ValueError):
        pass


    # Sinon, format "CLÉ:valeur,CLÉ:valeur"
    for token in raw.split(','):
        token = token.strip()
        if ':' not in token:
            continue
        key, _, value = token.partition(':')
        key   = key.strip().upper()
        value = value.strip()
        # Conversion numérique si possible
        try:
            entry[key] = float(value) if '.' in value else int(value)
        except ValueError:
            entry[key] = value


    return entry




def store_data(entry: dict):
    """Ajoute une entrée JSON sur une nouvelle ligne dans DATA_FILE."""
    with open(DATA_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')




def record_measurement(raw: str, udp_sock: socket.socket):
    """
    Appelé pour chaque ligne valide reçue du micro:bit :
      1. Parse les données.
      2. Met à jour l'état global.
      3. Persiste dans le fichier.
      4. Pousse la mesure vers tous les clients Android inscrits.
    """
    global latest_data, all_data


    if not raw:
        return


    entry = parse_sensor_line(raw)
    print(f"[DONNÉE] {entry}")


    # Mise à jour de l'état partagé
    with data_lock:
        latest_data = entry
        all_data.append(entry)


    store_data(entry)


    # Push vers les clients Android inscrits
    payload = json.dumps(entry).encode('utf-8')
    with clients_lock:
        dead = set()
        for addr in android_clients:
            try:
                udp_sock.sendto(payload, addr)
                print(f"[UDP]    Push → Android {addr}")
            except Exception as e:
                print(f"[UDP]    Push échoué vers {addr} : {e}")
                dead.add(addr)
        android_clients -= dead   # Retire les adresses mortes




# ============================================================
# THREAD DE LECTURE SÉRIE
# ============================================================


def serial_reader_thread(ser, udp_sock: socket.socket):
    """
    Tourne en permanence dans son propre thread.
    Lit chaque ligne reçue du micro:bit et déclenche record_measurement().


    Si 'ser' est None (mode simulation), le thread tourne à vide
    — le serveur UDP reste opérationnel.
    """
    print("[SÉRIE]  Thread de lecture démarré")


    while True:
        # --- Mode simulation : rien à lire, on attend ---
        if ser is None:
            time.sleep(1)
            continue


        try:
            raw_bytes = ser.readline()       # Bloque jusqu'à '\\n' ou timeout=1s
            if not raw_bytes:
                continue


            raw = raw_bytes.decode('utf-8', errors='ignore').strip()
            if raw:
                record_measurement(raw, udp_sock)


        except serial.SerialException as e:
            print(f"[SÉRIE]  Erreur de lecture : {e} — nouvelle tentative dans 2 s")
            time.sleep(2)
        except Exception as e:
            print(f"[SÉRIE]  Erreur inattendue : {e}")




# ============================================================
# TRAITEMENT DES MESSAGES UDP
# ============================================================


def is_valid_display_config(text: str) -> bool:
    """
    Valide une configuration d'affichage.
    Règles : uniquement des lettres de VALID_SENSORS, sans répétition, longueur >= 1.
    Exemples valides   : "T", "TL", "TLH", "TLHP", "HTP", ...
    Exemples invalides : "TT", "XYZ", "", "getValues()"
    """
    if not text:
        return False
    upper = text.upper()
    letters = set(upper)
    return (
        letters.issubset(VALID_SENSORS)
        and len(upper) == len(letters)   # Pas de répétition
    )




def handle_message(message: str, addr: tuple, udp_sock: socket.socket, ser):
    """
    Traite un message UDP reçu de l'application Android.


    Paramètres :
      message  : texte décodé reçu
      addr     : (ip, port) de l'expéditeur
      udp_sock : socket UDP pour les réponses
      ser      : objet Serial (ou None en simulation)
    """


    def reply(data):
        """Envoie une réponse JSON au client."""
        udp_sock.sendto(json.dumps(data, ensure_ascii=False).encode('utf-8'), addr)


    # --- Requête de la dernière mesure ---
    if message == "getValues()":
        with data_lock:
            response = latest_data if latest_data else {"message": "Aucune donnée disponible"}
        reply(response)
        print(f"[UDP]    getValues() → {addr}")


    # --- Requête de l'historique (10 dernières mesures) ---
    elif message == "getHistory()":
        with data_lock:
            history = list(all_data)[-10:]
        reply(history)
        print(f"[UDP]    getHistory() → {addr} ({len(history)} entrées)")


    # --- Inscription au push temps réel ---
    elif message == "register":
        with clients_lock:
            android_clients.add(addr)
        reply({"status": "ok", "message": "Inscrit au push temps réel"})
        print(f"[UDP]    register → {addr} inscrit")


    # --- Désinscription du push ---
    elif message == "unregister":
        with clients_lock:
            android_clients.discard(addr)
        reply({"status": "ok", "message": "Désinscrit"})
        print(f"[UDP]    unregister → {addr} désinscrit")


    # --- Configuration d'affichage (ex: "TLH", "HTP") ---
    elif is_valid_display_config(message):
        config = message.upper()
        success = send_to_microbit(ser, config)
        reply({"status": "ok" if success else "error", "config": config})
        print(f"[UDP]    config '{config}' → micro:bit (succès={success})")


    # --- Commande inconnue ---
    else:
        reply({"status": "error", "message": f"Commande inconnue : {message!r}"})
        print(f"[UDP]    Commande inconnue de {addr} : {message!r}")




# ============================================================
# SERVEUR UDP
# ============================================================


def udp_server(udp_sock: socket.socket, ser):
    """
    Boucle principale du serveur UDP.
    Tourne dans le thread principal et dispatch chaque message reçu
    dans un sous-thread pour ne pas bloquer les autres clients.
    """
    print(f"[UDP]    Serveur en écoute sur le port {UDP_PORT}\n")


    while True:
        try:
            data, addr = udp_sock.recvfrom(4096)
            message = data.decode('utf-8', errors='ignore').strip()


            threading.Thread(
                target=handle_message,
                args=(message, addr, udp_sock, ser),
                daemon=True,
            ).start()


        except (OSError, KeyboardInterrupt):
            # Socket fermé lors de l'arrêt ou Ctrl+C
            break
        except Exception as e:
            print(f"[UDP]    Erreur serveur : {e}")




# ============================================================
# POINT D'ENTRÉE
# ============================================================


def print_banner():
    print()
    print("=" * 55)
    print("   Passerelle / Serveur IoT — Mini Projet 2026")
    print("=" * 55)
    print(f"  Port UDP         : {UDP_PORT}")
    print(f"  Port série       : {SERIAL_PORT}  (baud={SERIAL_BAUD})")
    print(f"  Fichier données  : {os.path.abspath(DATA_FILE)}")
    print()
    print("  Commandes UDP supportées :")
    print("    getValues()     → dernière mesure")
    print("    getHistory()    → 10 dernières mesures")
    print("    register        → s'inscrire au push temps réel")
    print("    unregister      → se désinscrire du push")
    print("    TLH / HTP /…    → ordre d'affichage OLED")
    print("=" * 55)
    print()




def main():
    print_banner()


    # 1. Ouvre le port série (retourne None si indisponible → mode simulation)
    ser = open_serial()


    # 2. Crée et lie le socket UDP
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        udp_sock.bind((UDP_IP, UDP_PORT))
    except OSError as e:
        print(f"[ERREUR] Impossible d'écouter sur le port {UDP_PORT} : {e}")
        sys.exit(1)


    # 3. Démarre le thread de lecture série
    t = threading.Thread(
        target=serial_reader_thread,
        args=(ser, udp_sock),
        daemon=True,
        name="SerialReader",
    )
    t.start()


    # 4. Lance le serveur UDP dans le thread principal
    try:
        udp_server(udp_sock, ser)
    except KeyboardInterrupt:
        print("\n[INFO]   Arrêt demandé (Ctrl+C)...")
    finally:
        udp_sock.close()
        if ser:
            ser.close()
        print("[INFO]   Serveur arrêté proprement.")




if __name__ == "__main__":
    main()
