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
latest_payload = b""  # dernière trame JSON reçue du micro:bit (stockée en mémoire pour pouvoir la renvoyer rapidement à l'appli android sans aller chercher en base)
thread_lock    = threading.Lock() # évite que le thread UART et le thread UDP
                                   # écrivent/lisent latest_payload en même temps

# ============================================================
# SÉCURITÉ UART
# Clé identique à CLE_UART dans le firmware GW
# ============================================================
CLE_UART = bytes([0x55, 0x41, 0x52, 0x54, 0x32, 0x30, 0x32, 0x36])  # "UART2026"

# xorshift32 génère le prochain nombre pseudo-aléatoire du flux en mélangeant les bits de l'état courant.

#Serveur doit déchiffrer ce que la passerelle envoie
def xorshift32(etat): #génère des nombres pseudos-aléatoires    
    # Les trois décalages XOR sont identiques à ceux du firmware C++ passerelle (sinon déchiffrement fait n'importe quoi).
    etat ^= (etat << 13) & 0xFFFFFFFF #décalage tous les bits d'état de 13 vers la gauche, force résultat à être sur 32 bits
    etat ^= (etat >> 17) & 0xFFFFFFFF #XOR entre état et le état décalé (avec lui même) pour le mélanger 
    etat ^= (etat << 5)  & 0xFFFFFFFF
    return etat & 0xFFFFFFFF

def initialiser_prng(cle, nonce):
# Construit l'état de départ du générateur à partir de la clé et du nonce 
# deux trames identiques donnent des résultats chiffrés différents grâce au nonce.
    etat = (
        (cle[0] << 24) ^ #on prend U A R T et on les assemble en 1 entier de 32 bits (ici c'est U )
        (cle[1] << 16) ^
        (cle[2] << 8)  ^
        (cle[3])
    )
    etat ^= ((nonce << 16) | nonce) & 0xFFFFFFFF
    if etat == 0: # si masque + XOR on force valeur de départ
        etat = 0xA5A5A5A5
    return etat & 0xFFFFFFFF

# Calcule une empreinte 16 bits de la trame  si un octet change en transit, le CRC sera différent et la trame sera rejetée.
def calculer_crc16(data):
    crc = 0xFFFF # démarrage avec valeur maximale sur 16 bits (convention CR16)
    for b in data: # On parcourt chaque octet de la trame
        crc ^= b # Mélange octet courant dans le CRC avec un XOR
        for _ in range(8): # Pour chaque octet on fait 8 tours (un par bit)
            if crc & 1: # si bit plus à droite est à 1
                crc = (crc >> 1) ^ 0xA001  # on décale d'un bit vers la droite et on XOR avec 0xA001 (le bit "deborde" et pour compenser on XOR)
            else:
                crc >>= 1 #sinon on décale sans XOR 
    return crc & 0xFFFF

# Passerelle (émetteur) va calculer CRC de la trame et ajoute à la fin avant d'envoyer
# Serveur (Récepteur) recalcule CRC sur les octets reçus et compare avec celui qui était dans la trame  (si identique trame intacte) déchiffrement possible
# sinon erreur un octet a changé au moment de la transmission passerelle serveur

# Régénère le même flux de masques que la passerelle et XOR chaque octet chiffré pour retrouver le JSON original.
def dechiffrer_payload(payload_chiffre, nonce): 
    etat = initialiser_prng(CLE_UART, nonce) # m point départ que passerelle pour chiffrer. Clé "UART2026" et nonce même des 2 côtés pour déchiffrer
    result = bytearray() # tableau vide avec les octets déchiffrés (qu'il reçoit un par un)
    for b in payload_chiffre: # parcourt chaque octet chiffré 
        etat = xorshift32(etat) # décale le générateur d'un cran pour produire prochain nombre pseudo aléatoire
        masque = etat & 0xFF #8 bits les + à droite masque utilisé pour chiffrer
        result.append(b ^ masque) # XOR octet chiffré avec le m masque, propriété XOR 2 fois la m opération annule l'effet (on retrouve l'octet original)
    return result # retourne tableau déchiffré contient JSON en clair 

# ============================================================
# LECTURE TRAME UART BINAIRE (format trame que passerelle envoie vers serveur)
# Format :
#   [0]        = 0xC3          marqueur de début de trame 
#   [1..2]     = nonce UART    uint16_t little-endian 
#   [3]        = taille payload (combien d'octets chiffrés)
#   [4..N]     = payload JSON chiffré
#   [N+1..N+2] = CRC16 de la trame         little-endian
# ============================================================
# Lit le port série octet par octet, attend le marqueur 0xC3, 
# extrait le nonce, le payload et le CRC, vérifie l'intégrité, puis déchiffre et retourne le JSON en clair.
def lire_trame_uart(serial_conn):
    # Synchronisation sur le marqueur 0xC3
    while True:
        b = serial_conn.read(1) # lecture 1 octet à la fois (boucle infini jusqu'à ce qu'on trouve ce qu'on cherche)
        if not b:
            return None, None # Si microbit renvoie rien pendant plus d'une seconde (on sort de la fonction en renvoyant None)
        # Lignes texte envoyées avant le chiffrement UART (ex: radio_chiffre: XX XX ...)
        if b[0] == ord('\n') or b[0] == ord('\r'): # Si octet retour à la ligne on ignore et on passe au suivant
            continue
        if b[0] != 0xC3: # Si octet est pas marqueur de début 0xC3 (passerelle envoie 0xC3 + ligne de chiffrement montrant octets radio avant chiffrement)
            # Octet texte — on accumule jusqu'au \n pour afficher la ligne complète (de chiffrement qu'envoie la passerelle)
            ligne = bytearray([b[0]]) 
            while True:
                c = serial_conn.read(1)
                if not c or c[0] == ord('\n'): # donc lecture octet par octet jusqu'à arriver à \n pour afficher ligne entière
                    break
                ligne.append(c[0])
            texte_ligne = ligne.decode('utf-8', errors='ignore').strip() # si octet correspond à aucun caractère UTF-8 il est ignoré
            if texte_ligne: # Vérifie si ligne est pas vide
                print(f"[GW RAW] {texte_ligne}")
            continue # toujours pas trouvé le 0xC3 on refait la boucle 
        break

    # Lecture nonce (2 octets) + taille payload (1 octet)
    header = serial_conn.read(3) 
    if len(header) < 3: # Si on a reçu - de 3 octets (trame incomplète -> abandon)
        return None, None

    nonce  = int.from_bytes(header[0:2], 'little') # convertit 2 premiers octets en entier, little c'est bit moins significatif arrive en 1er
    taille = header[2] # 3 ème octets indique cb d'octest chiffrés arrivent

    # Lecture payload chiffré + CRC16 (CRC en 2 octets)
    reste = serial_conn.read(taille + 2) 
    if len(reste) < taille + 2: # Si pas tout reçu -> abandon
        return None, None

    payload_chiffre = reste[:taille] # Extrait octets chiffrés sauf 2 derniers (CRC)
    crc_recu        = int.from_bytes(reste[taille:taille + 2], 'little') # Extrait le CRC et met en entier (2 derniers octets)

    # Vérification CRC16
    trame_sans_crc = bytes([0xC3]) + header + payload_chiffre # trame sans CRC pour recalculer empreinte
    crc_calcule    = calculer_crc16(trame_sans_crc) # calcule crc

    if crc_calcule != crc_recu: # si 2 crc différents
        # Trame corrompue en transit ou paquet radio parasite, on l'ignore
        # et on attend la suivante sans couper le serveur.
        print(f"[ERREUR] CRC16 invalide (reçu={crc_recu:#06x}, calculé={crc_calcule:#06x})")
        return None, None

    # Affichage hex du payload UART chiffré
    hex_chiffre = ' '.join(f'{b:02X}' for b in payload_chiffre)
    print(f"[UART CHIFFRÉ]   nonce={nonce} | {hex_chiffre}")

    # Déchiffrement
    payload_clair = dechiffrer_payload(payload_chiffre, nonce) # Appelle fonction déchiffrement avec payload chiffré + nonce (renvoie octet en clair)
    texte = payload_clair.decode('utf-8', errors='ignore') # Convertit octet déchiffrés en texte lisible 

    print(f"[UART DÉCHIFFRÉ] {texte}")

    return texte, nonce

# ============================================================
# GESTION DE LA BASE DE DONNÉES
# ============================================================
#exécute n'importe quelle requête SQL et referme proprement la connexion après, pour ne pas répéter ce code partout dans le fichier.
def run_sql_query(sql, args=(), fetch_single=False, fetch_multiple=False):
    db_conn = sqlite3.connect(DB_FILE) # Ouvre connexion à la bdd Sqlite (chaque appel ouvre et referme sa connexion)
    c = db_conn.cursor() # Création du curseur pour envoie des requêtes à la base
    res = None # Initialiser à none pour si requete retourne rien (ex: Insert)
    try:
        c.execute(sql, args)
        if fetch_single: # Si 1 ligne (ex chercher capteur par id) on récup juste la 1ère ligne
            res = c.fetchone()
        elif fetch_multiple: # Si toutes les lignes (ex: récupérer historique), on récup tout
            res = c.fetchall()
        else:
            db_conn.commit() # Sinon si insert ou update on fait commit pour save les modifs
    except sqlite3.Error as err: # Si requête plante on affiche erreur sans faire crash le serv
        print(f"[ERREUR BDD] {err}")
    finally:
        db_conn.close() # Ferme connexion dans tous les cas 
    return res # Retourne les résultats soit none pour insert / update soit 1 ligne soit plusieurs lignes

# Cherche si capteur existe déjà en base, et sinon elle crée automatiquement. 
# Dans les deux cas elle retourne id du capteur dans la table Module_IoT.
def get_or_register_device(num_capteur):
    network_id = f"capteur_{num_capteur}" # Nom réseau du capteur, si numcapteur=1 alors capteur1 (id texte stocké en base)
    record = run_sql_query(
        "SELECT id FROM Module_IoT WHERE num_capteur = ?",
        (num_capteur,),
        fetch_single=True
    ) # cherche en base si ce num capteur existe déjà (le fetch single=true pcq on veut max 1 ligne de retour)
    if record is not None: # si capteur trouvé, on retourne son id
        return record[0] # record et pas fetchone car (fetch one retourne un tuple) et le record[0] car 1er élément c'est un id

    # Sinon capteur existe pas on insère en base 
    run_sql_query(
        "INSERT INTO Module_IoT (num_capteur, id_reseau, format_affichage) VALUES (?, ?, ?)",
        (num_capteur, network_id, "TLHP") # TLHP format d'affichage par défaut
    )
    new_record = run_sql_query(
        "SELECT id FROM Module_IoT WHERE num_capteur = ?",
        (num_capteur,),
        fetch_single=True
    ) # On récup l'id du nouveau capteur créer 
    # renvoie du nouvel id créer
    return new_record[0] if new_record else None # le if c'est si insert a fail ça renvoie none plutôt qu'un crash

# Enregistre chaque échange de communication (UART ou UDP) dans la table Journal_Trafic avec un horodatage.
def record_traffic_log(interface_type, comm_direction, target_details, raw_payload):
    horodatage = datetime.now().strftime('%Y-%m-%d %H:%M:%S') # Reformate l'heure actuelle et affiche en texte lisible (en base)
    query = "INSERT INTO Journal_Trafic (canal, sens_flux, infos_source, payload_brut, horodatage) VALUES (?, ?, ?, ?, ?)"
    run_sql_query(query, (interface_type, comm_direction, str(target_details), raw_payload, horodatage)) # éxecute la requête avec valeur dans l'ordre

#Elle prend les valeurs brutes reçues du micro:bit, les convertit dans les bonnes unités, et les insère dans la table Historique_Donnees.
def save_sensor_data(num_capteur, t_val, l_val, h_val, p_val):
    # Le firmware envoie t et h en centièmes d'unité (ex: 2502 = 25.02°C)
    # et p directement en hPa. On divise ici avant d'insérer en base (pareil pour humidité).
    t_celsius = t_val / 100.0
    h_percent = h_val / 100.0
    p_hpa     = p_val / 100.0

    network_id = f"capteur_{num_capteur}"  # Nom réseau du capteur, si numcapteur=1 alors capteur1 (id texte stocké en base)

    dev_id = get_or_register_device(network_id) # Récup id du capteur dans module_iot (si capteur existe pas, alors créer automatiquement)
    if not dev_id: # Si id pas pu être récup alors on arrête sans insérer
        print(f"[ERREUR] ID introuvable pour le réseau {network_id}")
        return

    horodatage = datetime.now().strftime('%Y-%m-%d %H:%M:%S') # Horodatage au moment de l'insertion

    run_sql_query(
        "INSERT INTO Historique_Donnees (module_id, val_temp, val_lum, val_hum, val_pres, horodatage, ts_unix) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (dev_id, t_celsius, l_val, h_percent, p_hpa, horodatage, int(time.time()))
    )
    # Insertion mesure avec val converties. int(time.time()) timestamp unix en secondes, pour grafana affichage des courbes avec bonne dates
    print(f"[BDD] Capteur {num_capteur} ({horodatage}) -> Temp:{t_celsius}°C Hum:{h_percent}% Pres:{p_hpa}hPa Lum:{l_val}lux\n")

# ============================================================
# PARSING DES TRAMES (texte déjà déchiffré)
# ============================================================
# Elle reçoit le JSON déchiffré, le parse, met à jour la dernière valeur en mémoire, sauvegarde dans le fichier texte, et insère en base.
def parse_incoming_data(raw_line, active_port):
    global latest_payload # modif variable global 
    clean_line = raw_line.strip() # supprime espace et retour à la ligne en début et fin de texte

    if len(clean_line) == 0: # si ligne vide après nettoyage c'est qu'il y a rien donc on sort
        return

    record_traffic_log("UART", "RX", active_port, clean_line) # Enregistre la reception dans trafic log

    try:
        json_payload  = json.loads(clean_line) # parse le texte json en dictionnaire python (clé - valeur)
        required_keys = ["id", "t", "h", "p", "l"] # liste des clés attendus dans trame (si 1 manque trame incomplète)

        if all(key in json_payload for key in required_keys): # Vérifie si toutes clés attendus sont là dans le JSON
            with thread_lock: # agit comme un mutex thread UDP peut pas lire en m temps 
                latest_payload = clean_line.encode('utf-8') # met à jour dernière mesure en mémoire + reconvertit le texte en UTF-8

            with open(BACKUP_TXT, "a", encoding='utf-8') as backup:
                backup.write(clean_line + "\n")

            save_sensor_data(
                json_payload["id"],
                json_payload["t"],
                json_payload["l"],
                json_payload["h"],
                json_payload["p"]
            ) # Appelle fonction d'insertion en base avec les valeurs JSON
        else:
            print(f"[ATTENTION] Trame incomplète : {clean_line}")

    except json.JSONDecodeError: # Si json_loads échoue car pas Json valide, alors alerte sans faire planter le serv
        print(f"[ATTENTION] Format non-JSON : {clean_line}")

# ============================================================
# GESTION DU PORT SÉRIE
# ============================================================
# Elle parcourt tous les ports série disponibles sur le PC et retourne automatiquement celui du micro:bit s'il est branché.
def detect_serial_port():
    available_ports = serial.tools.list_ports.comports() # Récupère la liste de tous les ports série connectés au PC 
    for p in available_ports: # Parcourt chaque port trouvé un par un.
        p_desc = p.description.lower() # Récupère la description du port en minuscules
        if any(keyword in p_desc for keyword in ["mbed", "microbit", "usb serial device"]): # vérifie si description a un des mots-clés 
            return p.device # retourne le nom du port trouvé ex(COM4)
    return None # Si aucun port trouvé, renvoie none et utilise le port par défaut (COM_PORT)

# Configure et ouvre la connexion série avec le micro:bit passerelle, et arrête le programme si la connexion échoue.
def connect_gateway():
    target_port = detect_serial_port() # Appelle la fonction de détection automatique du port micro:bit.
    if target_port is None:
        target_port = COM_PORT # Si aucun port trouvé utilise le port par défaut (COM_PORT)

    gateway_serial          = serial.Serial() # Objet Serial vide (pas encore connecté, on config d'abord les paramètres)
    gateway_serial.port     = target_port # Définit le port à utiliser
    gateway_serial.baudrate = BAUD_RATE # Définit vitesse à utiliser (identique côté serveur et passerelle), sinon données illisibles
    gateway_serial.timeout  = 1 # si read reçoit rien pdnt 1 sec, il retourne quand même au lieu de bloquer 

    print(f"[UART] Tentative de connexion sur {target_port} ({BAUD_RATE} baud)...")
    try:
        gateway_serial.open() # Ouvre connexion série avec le micro:bit
        print("[UART] Gateway connectée avec succès.")
    except serial.SerialException as err: # Si ouverture échoue (microbit pas branché, port déjà utilisé), affichage erreur
        print(f"[UART] Échec d'ouverture du port {target_port} : {err}")
        sys.exit(1) # arret du programme impossible sans passarelle

    return gateway_serial

# Elle retransmet la commande de configuration reçue de l'Android (comme "TLHP") 
# au micro:bit passerelle via le port série, qui la relayera ensuite par radio à l'objet capteur.
def transmit_serial_msg(gateway, text_command):
    formatted_cmd = (text_command.strip() + '\r\n').encode('utf-8') # prépare la commande
    # strip (supprime espace parasite), + '\r\n' ajout retour à la ligne pour que microbit sache que commande est terminée
    # .encode('utf-8') convertit texte en octet, car port série envoie octet pas texte
    gateway.write(formatted_cmd) # Envoie octets sur port série vers micro:bit GW.
    record_traffic_log("UART", "TX", gateway.port, text_command) # Trace l'envoi dans Journal_Trafic — canal UART, sens TX (envoyé).
    print(f"[UART] -> Envoi vers Micro:bit : {text_command!r}")

def check_format_validity(config_str):
    # vérifie que la commande envoyée par l'Android ne contient que les lettres autorisées T, L, H, P sans répétition, 
    # avant de la transmettre à la passerelle. Ça évite qu'un client envoie n'importe quelle
    # chaîne qui serait ensuite transmise telle quelle sur l'UART.
    if not config_str: # Si commande vide, alors invalide donc renvoie false
        return False
    formatted = config_str.upper() # met tout en majuscule pour accepter tlhp
    char_set  = set(formatted) # créer un ensemble des lettres de la commande. Un set supprime automatiquement les doublons (ex TTL = 'T', 'L')
    return char_set.issubset(ALLOWED_CHARS) and len(formatted) == len(char_set)
    # char_set.issubset(ALLOWED_CHARS): Vérifie que toutes les lettres sont dans allowed chars qui contient (TLHP)
    # and len(formatted) == len(char_set): Vérifie s'il y a pas de répétitions (ex TTL, 3 caractères) mais char_set vaut 2 (T et L)
    # taille différente donc commande rejetée

# ============================================================
# GESTIONNAIRE RÉSEAU UDP
# ============================================================
#Elle traite chaque message UDP reçu de l'Android et agit selon le contenu : 
# renvoie les dernières valeurs si c'est getValues(), ou transmet la config à la passerelle si c'est une commande valide.
class ClientRequestHandler(socketserver.BaseRequestHandler):
    def handle(self):
        global latest_payload
        incoming_bytes = self.request[0].strip() # Récupère les données brutes reçues en UDP.
        udp_socket     = self.request[1] # Récupère le socket pour pouvoir répondre à l'Android.
        decoded_msg    = incoming_bytes.decode('utf-8', errors='ignore').strip() # Convertit les octets reçus en texte lisible.

        sender_ip_port = f"{self.client_address[0]}:{self.client_address[1]}" # Construit l'adresse de l'expéditeur au format "192.168.1.10:5000" — utile pour les logs.
        print(f"[UDP] <- Reçu de {sender_ip_port} : {decoded_msg!r}") 
        record_traffic_log("UDP", "RX", sender_ip_port, decoded_msg) # Trace la réception dans Journal_Trafic.

        if decoded_msg == "getValues()": # Si l'Android demande les dernières valeurs :
            # # Récupère la dernière mesure en mémoire de façon sécurisée avec le mutex. 
            # Si aucune mesure n'est encore arrivée, on renvoie un message d'attente.
            with thread_lock: 
                reply = latest_payload if latest_payload else b"Pas de donnees en memoire"
            udp_socket.sendto(reply, self.client_address)
            record_traffic_log("UDP", "TX", sender_ip_port, reply.decode('utf-8', errors='ignore'))
            print(f"[UDP] -> Réponse à {sender_ip_port} : {reply!r}")

        elif check_format_validity(decoded_msg): # Si le message est une config valide comme "TLH" ou "TLHP"
            safe_config = decoded_msg.upper() # Met en majuscules pour être sûr.
            transmit_serial_msg(self.server.serial_conn, safe_config) # Transmet la config à la passerelle via UART — elle la relayera par radio à l'objet.

            confirmation = f'{{"status":"success","config":"{safe_config}"}}'.encode() # Prépare un message de réception JSON à renvoyer à l'Android.
            udp_socket.sendto(confirmation, self.client_address) # Envoie ce message de confirmation à l'Android.
            record_traffic_log("UDP", "TX", sender_ip_port, confirmation.decode())

        else:
            print(f"[UDP] Ordre non reconnu : {decoded_msg!r}") # Si le message ne correspond ni à getValues() ni à une config valide, on l'ignore.

class UDPGatewayServer(socketserver.ThreadingMixIn, socketserver.UDPServer): # Crée le serveur UDP avec support multi-threads. 
    pass #ThreadingMixIn fait que chaque requête UDP est traitée dans son propre thread — deux clients peuvent envoyer en même temps sans se bloquer.

# ============================================================
# BOUCLE PRINCIPALE
# ============================================================
# C'est le point d'entrée du programme — il ouvre le port série, démarre le serveur UDP dans un thread séparé, 
# puis entre dans la boucle principale qui lit en continu les trames du micro:bit.
if __name__ == '__main__': # Ce bloc ne s'exécute que si on lance directement controller.py. Si le fichier importé ailleurs, ce code ne s'exécute pas.
    serial_gateway = connect_gateway() # Ouvre la connexion série avec le micro:bit passerelle.

    udp_server = UDPGatewayServer((BIND_IP, LISTEN_PORT), ClientRequestHandler) # Crée serveur UDP qui écoute port 10005
    # ClientRequestHandler qui gère message reçu
    udp_server.serial_conn = serial_gateway # Partage port série avec handler UDP pour transmettre config à la passerelle

    bg_thread        = threading.Thread(target=udp_server.serve_forever) # Crée un thread dédié au serveur UDP.
    bg_thread.daemon = True # Le thread s'arrête automatiquement quand le programme principal s'arrête.
    bg_thread.start() # Démarre le thread UDP, serveur écoute requête android en arrière plan, pendant que boucle principale lit port série

    print(f"*** Serveur UDP en écoute sur le port {LISTEN_PORT} ***")
    print(">>> Appuyez sur Ctrl+C pour interrompre le script. <<<\n")

    try:
        while serial_gateway.isOpen(): # Boucle tant que le port série est ouvert.
            if serial_gateway.in_waiting > 0:  # Vérifie si des données sont disponibles sur le port série.
                texte, _ = lire_trame_uart(serial_gateway) # Lit et déchiffre une trame complète depuis la passerelle
                if texte:
                    parse_incoming_data(texte, serial_gateway.port) # Si la trame est valide, on la parse et on insère en base.
            else:
                time.sleep(0.05) # Rien à lire — on attend 50ms pour ne pas saturer le CPU pour rien.

    except (KeyboardInterrupt, SystemExit): # Intercepte le Ctrl+C pour arrêter proprement.
        print("\n[SYSTEM] Séquence d'arrêt initiée...")
    finally:
        udp_server.shutdown()
        udp_server.server_close()
        serial_gateway.close()
        print("[SYSTEM] Fermeture complète des ports et du serveur.")
        # S'exécute dans tous les cas — même en cas d'erreur. Ferme le serveur UDP et le port série proprement.