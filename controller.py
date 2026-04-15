#!/usr/bin/env python3
import time
import sys
import socketserver
import threading
import sqlite3
import json
from datetime import datetime # Ajouté pour l'horodatage

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
LISTEN_PORT   = 10000
COM_PORT      = "COM3" # Modifie ceci selon ton système
BAUD_RATE     = 115200

DB_FILE       = "iot_project.db"
BACKUP_TXT    = "values.txt"

ALLOWED_CHARS = set("TLHP")
latest_payload = b""
thread_lock    = threading.Lock()

# ============================================================
# GESTION DE LA BASE DE DONNÉES (Requêtes uniquement)
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

def get_or_register_device(network_id):
    record = run_sql_query("SELECT id FROM Module_IoT WHERE id_reseau = ?", (network_id,), fetch_single=True)
    if record is not None:
        return record[0]
    
    run_sql_query("INSERT INTO Module_IoT (id_reseau, format_affichage) VALUES (?, ?)", (network_id, "THLP"))
    new_record = run_sql_query("SELECT id FROM Module_IoT WHERE id_reseau = ?", (network_id,), fetch_single=True)
    return new_record[0] if new_record else None

def record_traffic_log(interface_type, comm_direction, target_details, raw_payload):
    # Ajout de l'horodatage local
    horodatage = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    query = "INSERT INTO Journal_Trafic (canal, sens_flux, infos_source, payload_brut, horodatage) VALUES (?, ?, ?, ?, ?)"
    run_sql_query(query, (interface_type, comm_direction, str(target_details), raw_payload, horodatage))

def save_sensor_data(network_id, t_val, l_val, h_val, p_val):
    t_celsius = t_val / 100.0
    h_percent = h_val / 100.0
    p_hpa = p_val / 100.0
    
    dev_id = get_or_register_device(network_id)
    if not dev_id:
        print(f"[ERREUR] ID introuvable pour le réseau {network_id}")
        return

    # Ajout de l'horodatage local
    horodatage = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    insert_query = "INSERT INTO Historique_Donnees (module_id, val_temp, val_lum, val_hum, val_pres, horodatage) VALUES (?, ?, ?, ?, ?, ?)"
    run_sql_query(insert_query, (dev_id, t_celsius, l_val, h_percent, p_hpa, horodatage))
    
    # Correction du print pour afficher la luminosité (l_val)
    print(f"[BDD] Enregistrement ({horodatage}) -> Temp:{t_celsius}°C Hum:{h_percent}% Pres:{p_hpa}hPa Lum:{l_val}lux")

# ============================================================
# PARSING DES TRAMES SÉRIE
# ============================================================
def parse_incoming_data(raw_line, active_port):
    global latest_payload
    clean_line = raw_line.strip()
    
    if len(clean_line) == 0:
        return

    record_traffic_log("UART", "RX", active_port, clean_line)

    if "debug" in clean_line or "err" in clean_line:
        print(f"[INFO] Gateway dit : {clean_line}")
        return

    try:
        json_payload = json.loads(clean_line)
        required_keys = ["t", "h", "p", "l"]
        
        if all(key in json_payload for key in required_keys):
            with thread_lock:
                latest_payload = clean_line.encode('utf-8')
            
            with open(BACKUP_TXT, "a", encoding='utf-8') as backup:
                backup.write(clean_line + "\n")
            
            save_sensor_data("0xA1", json_payload["t"], json_payload["l"], json_payload["h"], json_payload["p"])
        else:
            print(f"[ATTENTION] Trame incomplète : {clean_line}")
            
    except json.JSONDecodeError:
        print(f"[ATTENTION] Format non-JSON reçu : {clean_line}")

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
        
    gateway_serial = serial.Serial()
    gateway_serial.port = target_port
    gateway_serial.baudrate = BAUD_RATE
    gateway_serial.timeout = 1
    
    print(f"[UART] Tentative de connexion sur {target_port} ({BAUD_RATE} baud)...")
    try:
        gateway_serial.open()
        print("[UART] Gateway connectée avec succès.")
    except serial.SerialException as err:
        print(f"[UART] Échec d'ouverture du port {target_port} : {err}")
        sys.exit(1)
        
    return gateway_serial

def transmit_serial_msg(gateway, text_command):
    # J'ai remis \r\n car sinon ton Microbit ne verra jamais la fin du message (lié au code C++)
    formatted_cmd = (text_command.strip() + '\r\n').encode('utf-8')
    gateway.write(formatted_cmd)
    record_traffic_log("UART", "TX", gateway.port, text_command)
    print(f"[UART] -> Envoi vers Micro:bit : {text_command!r}")

def check_format_validity(config_str):
    if not config_str:
        return False
    formatted = config_str.upper()
    char_set = set(formatted)
    return char_set.issubset(ALLOWED_CHARS) and len(formatted) == len(char_set)

# ============================================================
# GESTIONNAIRE RÉSEAU UDP
# ============================================================
class ClientRequestHandler(socketserver.BaseRequestHandler):
    def handle(self):
        global latest_payload
        incoming_bytes = self.request[0].strip()
        udp_socket = self.request[1]
        decoded_msg = incoming_bytes.decode('utf-8', errors='ignore').strip()

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
    
    udp_server = UDPGatewayServer((BIND_IP, LISTEN_PORT), ClientRequestHandler)
    udp_server.serial_conn = serial_gateway 

    bg_thread = threading.Thread(target=udp_server.serve_forever)
    bg_thread.daemon = True
    bg_thread.start()
    print(f"*** Serveur UDP en écoute sur le port {LISTEN_PORT} ***")
    print(">>> Appuyez sur Ctrl+C pour interrompre le script. <<<\n")

    try:
        while serial_gateway.isOpen():
            if serial_gateway.in_waiting > 0:
                raw_bytes = serial_gateway.readline()
                if raw_bytes:
                    parsed_text = raw_bytes.decode('utf-8', errors='ignore').strip()
                    if parsed_text:
                        parse_incoming_data(parsed_text, serial_gateway.port)
            else:
                time.sleep(0.05)
                
    except (KeyboardInterrupt, SystemExit):
        print("\n[SYSTEM] Séquence d'arrêt initiée...")
    finally:
        udp_server.shutdown()
        udp_server.server_close()
        serial_gateway.close()
        print("[SYSTEM] Fermeture complète des ports et du serveur.")