#!/usr/bin/env python3
import time
import sys
import socketserver
import threading
import sqlite3
import json
from datetime import datetime

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("[ERREUR] Le module pyserial est introuvable. Exécutez : pip install pyserial")
    sys.exit(1)

# ============================================================
# PARAMÈTRES DE CONFIGURATION
# ============================================================
BIND_IP       = "0.0.0.0"
LISTEN_PORT   = 10005
COM_PORT      = "COM4"
BAUD_RATE     = 115200

DB_FILE       = "iot_project.db"
BACKUP_TXT    = "values.txt"

ALLOWED_CHARS  = set("TLHP")
latest_payload = b""  # dernière trame JSON reçue du micro:bit
thread_lock    = threading.Lock() # évite que le thread UART et le thread UDP
                                   # écrivent/lisent latest_payload en même temps

# ============================================================
# SÉCURITÉ UART
# Clé identique à CLE_UART dans le firmware GW
# ============================================================
CLE_UART = bytes([0x55, 0x41, 0x52, 0x54, 0x32, 0x30, 0x32, 0x36])  # "UART2026"

def xorshift32(etat):
    # Les trois décalages XOR sont identiques à ceux du firmware C++ passerelle.
    etat ^= (etat << 13) & 0xFFFFFFFF
    etat ^= (etat >> 17) & 0xFFFFFFFF
    etat ^= (etat << 5)  & 0xFFFFFFFF
    return etat & 0xFFFFFFFF

def initialiser_prng(cle, nonce):
    # Construit l'état initial du PRNG à partir de la clé et du nonce.
    # Comme le nonce change à chaque trame donc  deux trames avec le même
    # contenu JSON produiront des octets chiffrés différents.
    etat = (
        (cle[0] << 24) ^
        (cle[1] << 16) ^
        (cle[2] << 8)  ^
        (cle[3])
    )
    etat ^= ((nonce << 16) | nonce) & 0xFFFFFFFF
    if etat == 0:
        etat = 0xA5A5A5A5
    return etat & 0xFFFFFFFF

def calculer_crc16(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF

def dechiffrer_payload(payload_chiffre, nonce):
    etat = initialiser_prng(CLE_UART, nonce)
    result = bytearray()
    for b in payload_chiffre:
        etat = xorshift32(etat)
        masque = etat & 0xFF
        result.append(b ^ masque)
    return result

# ============================================================
# LECTURE TRAME UART BINAIRE
# Format :
#   [0]        = 0xC3          marqueur de début
#   [1..2]     = nonce UART    uint16_t little-endian
#   [3]        = taille payload
#   [4..N]     = payload JSON chiffré
#   [N+1..N+2] = CRC16         little-endian
# ============================================================
def lire_trame_uart(serial_conn):
    # Synchronisation sur le marqueur 0xC3
    while True:
        b = serial_conn.read(1)
        if not b:
            return None, None
        # Lignes texte envoyées avant le chiffrement UART (ex: radio_chiffre: XX XX ...)
        if b[0] == ord('\n') or b[0] == ord('\r'):
            continue
        if b[0] != 0xC3:
            # Octet texte — on accumule jusqu'au \n pour afficher la ligne complète
            ligne = bytearray([b[0]])
            while True:
                c = serial_conn.read(1)
                if not c or c[0] == ord('\n'):
                    break
                ligne.append(c[0])
            texte_ligne = ligne.decode('utf-8', errors='ignore').strip()
            if texte_ligne:
                print(f"[GW RAW] {texte_ligne}")
            continue
        break

    # Lecture nonce (2 octets) + taille payload (1 octet)
    header = serial_conn.read(3)
    if len(header) < 3:
        return None, None

    nonce  = int.from_bytes(header[0:2], 'little')
    taille = header[2]

    # Lecture payload chiffré + CRC16
    reste = serial_conn.read(taille + 2)
    if len(reste) < taille + 2:
        return None, None

    payload_chiffre = reste[:taille]
    crc_recu        = int.from_bytes(reste[taille:taille + 2], 'little')

    # Vérification CRC16
    trame_sans_crc = bytes([0xC3]) + header + payload_chiffre
    crc_calcule    = calculer_crc16(trame_sans_crc)

    if crc_calcule != crc_recu:
        # Trame corrompue en transit ou paquet radio parasite, on l'ignore
        # et on attend la suivante sans couper le serveur.
        print(f"[ERREUR] CRC16 invalide (reçu={crc_recu:#06x}, calculé={crc_calcule:#06x})")
        return None, None

    # Affichage hex du payload UART chiffré
    hex_chiffre = ' '.join(f'{b:02X}' for b in payload_chiffre)
    print(f"[UART CHIFFRÉ]   nonce={nonce} | {hex_chiffre}")

    # Déchiffrement
    payload_clair = dechiffrer_payload(payload_chiffre, nonce)
    texte = payload_clair.decode('utf-8', errors='ignore')

    print(f"[UART DÉCHIFFRÉ] {texte}")

    return texte, nonce

# ============================================================
# GESTION DE LA BASE DE DONNÉES
# ============================================================
def run_sql_query(sql, args=(), fetch_single=False, fetch_multiple=False):
    db_conn = sqlite3.connect(DB_FILE)
    c = db_conn.cursor()
    res = None
    try:
        c.execute(sql, args)
        if fetch_single:
            res = c.fetchone()
        elif fetch_multiple:
            res = c.fetchall()
        else:
            db_conn.commit()
    except sqlite3.Error as err:
        print(f"[ERREUR BDD] {err}")
    finally:
        db_conn.close()
    return res

def get_or_register_device(num_capteur):
    network_id = f"capteur_{num_capteur}"
    record = run_sql_query(
        "SELECT id FROM Module_IoT WHERE num_capteur = ?",
        (num_capteur,),
        fetch_single=True
    )
    if record is not None:
        return record[0]

    run_sql_query(
        "INSERT INTO Module_IoT (num_capteur, id_reseau, format_affichage) VALUES (?, ?, ?)",
        (num_capteur, network_id, "TLHP")
    )
    new_record = run_sql_query(
        "SELECT id FROM Module_IoT WHERE num_capteur = ?",
        (num_capteur,),
        fetch_single=True
    )
    return new_record[0] if new_record else None

def record_traffic_log(interface_type, comm_direction, target_details, raw_payload):
    horodatage = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    query = "INSERT INTO Journal_Trafic (canal, sens_flux, infos_source, payload_brut, horodatage) VALUES (?, ?, ?, ?, ?)"
    run_sql_query(query, (interface_type, comm_direction, str(target_details), raw_payload, horodatage))

def save_sensor_data(num_capteur, t_val, l_val, h_val, p_val):
    # Le firmware envoie t et h en centièmes d'unité (ex: 2502 = 25.02°C)
    # et p directement en hPa. On divise ici avant d'insérer en base.
    t_celsius = t_val / 100.0
    h_percent = h_val / 100.0
    p_hpa     = p_val / 100.0

    network_id = f"capteur_{num_capteur}"

    dev_id = get_or_register_device(network_id)
    if not dev_id:
        print(f"[ERREUR] ID introuvable pour le réseau {network_id}")
        return

    horodatage = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    run_sql_query(
        "INSERT INTO Historique_Donnees (module_id, val_temp, val_lum, val_hum, val_pres, horodatage, ts_unix) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (dev_id, t_celsius, l_val, h_percent, p_hpa, horodatage, int(time.time()))
    )

    print(f"[BDD] Capteur {num_capteur} ({horodatage}) -> Temp:{t_celsius}°C Hum:{h_percent}% Pres:{p_hpa}hPa Lum:{l_val}lux\n")

# ============================================================
# PARSING DES TRAMES (texte déjà déchiffré)
# ============================================================
def parse_incoming_data(raw_line, active_port):
    global latest_payload
    clean_line = raw_line.strip()

    if len(clean_line) == 0:
        return

    record_traffic_log("UART", "RX", active_port, clean_line)

    try:
        json_payload  = json.loads(clean_line)
        required_keys = ["id", "t", "h", "p", "l"]

        if all(key in json_payload for key in required_keys):
            with thread_lock:
                latest_payload = clean_line.encode('utf-8')

            with open(BACKUP_TXT, "a", encoding='utf-8') as backup:
                backup.write(clean_line + "\n")

            save_sensor_data(
                json_payload["id"],
                json_payload["t"],
                json_payload["l"],
                json_payload["h"],
                json_payload["p"]
            )
        else:
            print(f"[ATTENTION] Trame incomplète : {clean_line}")

    except json.JSONDecodeError:
        print(f"[ATTENTION] Format non-JSON : {clean_line}")

# ============================================================
# GESTION DU PORT SÉRIE
# ============================================================
def detect_serial_port():
    available_ports = serial.tools.list_ports.comports()
    for p in available_ports:
        p_desc = p.description.lower()
        if any(keyword in p_desc for keyword in ["mbed", "microbit", "usb serial device"]):
            return p.device
    return None

def connect_gateway():
    target_port = detect_serial_port()
    if target_port is None:
        target_port = COM_PORT

    gateway_serial          = serial.Serial()
    gateway_serial.port     = target_port
    gateway_serial.baudrate = BAUD_RATE
    gateway_serial.timeout  = 1

    print(f"[UART] Tentative de connexion sur {target_port} ({BAUD_RATE} baud)...")
    try:
        gateway_serial.open()
        print("[UART] Gateway connectée avec succès.")
    except serial.SerialException as err:
        print(f"[UART] Échec d'ouverture du port {target_port} : {err}")
        sys.exit(1)

    return gateway_serial

def transmit_serial_msg(gateway, text_command):
    formatted_cmd = (text_command.strip() + '\r\n').encode('utf-8')
    gateway.write(formatted_cmd)
    record_traffic_log("UART", "TX", gateway.port, text_command)
    print(f"[UART] -> Envoi vers Micro:bit : {text_command!r}")

def check_format_validity(config_str):
    # Vérifie que la commande reçue par UDP ne contient que T, L, H, P
    # sans répétition. Ça évite qu'un client envoie n'importe quelle
    # chaîne qui serait ensuite transmise telle quelle sur l'UART.
    if not config_str:
        return False
    formatted = config_str.upper()
    char_set  = set(formatted)
    return char_set.issubset(ALLOWED_CHARS) and len(formatted) == len(char_set)

# ============================================================
# GESTIONNAIRE RÉSEAU UDP
# ============================================================
class ClientRequestHandler(socketserver.BaseRequestHandler):
    def handle(self):
        global latest_payload
        incoming_bytes = self.request[0].strip()
        udp_socket     = self.request[1]
        decoded_msg    = incoming_bytes.decode('utf-8', errors='ignore').strip()

        sender_ip_port = f"{self.client_address[0]}:{self.client_address[1]}"
        print(f"[UDP] <- Reçu de {sender_ip_port} : {decoded_msg!r}")
        record_traffic_log("UDP", "RX", sender_ip_port, decoded_msg)

        if decoded_msg == "getValues()":
            with thread_lock:
                reply = latest_payload if latest_payload else b"Pas de donnees en memoire"
            udp_socket.sendto(reply, self.client_address)
            record_traffic_log("UDP", "TX", sender_ip_port, reply.decode('utf-8', errors='ignore'))
            print(f"[UDP] -> Réponse à {sender_ip_port} : {reply!r}")

        elif check_format_validity(decoded_msg):
            safe_config = decoded_msg.upper()
            transmit_serial_msg(self.server.serial_conn, safe_config)

            confirmation = f'{{"status":"success","config":"{safe_config}"}}'.encode()
            udp_socket.sendto(confirmation, self.client_address)
            record_traffic_log("UDP", "TX", sender_ip_port, confirmation.decode())

        else:
            print(f"[UDP] Ordre non reconnu : {decoded_msg!r}")

class UDPGatewayServer(socketserver.ThreadingMixIn, socketserver.UDPServer):
    pass

# ============================================================
# BOUCLE PRINCIPALE
# ============================================================
if __name__ == '__main__':
    serial_gateway = connect_gateway()

    udp_server             = UDPGatewayServer((BIND_IP, LISTEN_PORT), ClientRequestHandler)
    udp_server.serial_conn = serial_gateway

    bg_thread        = threading.Thread(target=udp_server.serve_forever)
    bg_thread.daemon = True
    bg_thread.start()

    print(f"*** Serveur UDP en écoute sur le port {LISTEN_PORT} ***")
    print(">>> Appuyez sur Ctrl+C pour interrompre le script. <<<\n")

    try:
        while serial_gateway.isOpen():
            if serial_gateway.in_waiting > 0:
                texte, _ = lire_trame_uart(serial_gateway)
                if texte:
                    parse_incoming_data(texte, serial_gateway.port)
            else:
                time.sleep(0.05)

    except (KeyboardInterrupt, SystemExit):
        print("\n[SYSTEM] Séquence d'arrêt initiée...")
    finally:
        udp_server.shutdown()
        udp_server.server_close()
        serial_gateway.close()
        print("[SYSTEM] Fermeture complète des ports et du serveur.")