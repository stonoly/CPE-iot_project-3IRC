# Script de test — simule ce que le micro:bit enverrait via UART
# Ouvre le port série du micro:bit et envoie des données de test
# Utile pour vérifier que le serveur reçoit bien les données sans avoir le code micro:bit complet

import serial
import serial.tools.list_ports
import time

SERIAL_PORT = "COM3"   # Changez selon votre port (Gestionnaire de périphériques)
SERIAL_BAUD = 115200

def find_microbit():
    for port in serial.tools.list_ports.comports():
        desc = port.description.lower()
        if "mbed" in desc or "microbit" in desc or "micro:bit" in desc:
            print(f"micro:bit trouvé sur {port.device}")
            return port.device
    return None

port = find_microbit() or SERIAL_PORT

print(f"Connexion sur {port} à {SERIAL_BAUD} baud...")
ser = serial.Serial(port, SERIAL_BAUD, timeout=1)
print("Connecté. Envoi de données de test toutes les 2 secondes. Ctrl+C pour arrêter.\n")

try:
    i = 1
    while True:
        message = f"T:24.{i % 10},L:{300 + i},H:{55 + i % 10},P:1013"
        ser.write((message + '\n').encode('utf-8'))
        print(f"Envoyé → {message}")
        time.sleep(2)
        i += 1
except KeyboardInterrupt:
    print("\nArrêt.")
finally:
    ser.close()
