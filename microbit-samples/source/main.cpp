#include "MicroBit.h"
    
MicroBit uBit;

// --- FONCTION DE SÉCURITÉ ---
// Calcul de la somme de contrôle (Checksum) pour vérifier l'intégrité de la trame
uint8_t calculer_somme_controle(uint8_t* donnees, int taille) {
    uint8_t somme = 0;
    for (int idx = 0; idx < taille; idx++) {
        somme += donnees[idx];
    }
    return somme;
}

// --- RÉCEPTION RADIO ---
// Callback déclenché automatiquement dès que la passerelle reçoit un signal sans fil
void reception_trame_radio(MicroBitEvent) {
    uint8_t tampon_rx[32];
    int octets_recus = uBit.radio.datagram.recv(tampon_rx, 32);

    // On s'assure d'avoir la bonne taille (16 data + 1 CRC = 17) et le bon identifiant (0xA1)
    if (octets_recus == 17 && tampon_rx[0] == 0xA1) {
        
        uint8_t crc_calcule = calculer_somme_controle(tampon_rx, 16);
        
        // Vérification du bit de parité (CRC)
        if (crc_calcule != tampon_rx[16]) {
            uBit.serial.printf("{\"err\":\"Erreur de checksum CRC\"}\r\n");
            return;
        }

        // Création des variables de stockage temporaire
        int32_t val_temp;
        uint16_t val_hum;
        uint32_t val_press;
        uint32_t val_lum;

        // Extraction des valeurs à partir des indices de la trame
        memcpy(&val_temp, &tampon_rx[2], 4);
        memcpy(&val_hum, &tampon_rx[6], 2);
        memcpy(&val_press, &tampon_rx[8], 4);
        memcpy(&val_lum, &tampon_rx[12], 4);

        // Formatage en JSON et envoi via UART au script Python
        uBit.serial.printf("{\"t\": %d, \"h\": %d, \"p\": %d, \"l\": %d}\r\n", val_temp, val_hum, val_press, val_lum);
    }
}

// --- BOUCLE PRINCIPALE ---
int main() {
    uBit.init();
    uBit.radio.enable();
    
    // Configuration du canal de communication
    uBit.radio.setGroup(77); 

    // Lancement de l'écoute en arrière-plan
    uBit.messageBus.listen(MICROBIT_ID_RADIO, MICROBIT_RADIO_EVT_DATAGRAM, reception_trame_radio);

    // Message d'initialisation sur la matrice LED
    uBit.display.scroll("GW READY"); 

    while (true) {
        // Écoute du port série pour recevoir les instructions d'affichage
        ManagedString instruction = uBit.serial.readUntil("\r\n");

        if (instruction.length() > 0) {
            int longueur_cmd = instruction.length();
            
            // --- CORRECTION ICI ---
            // On accepte jusqu'à 5 pour tolérer le \r (retour chariot) envoyé par certains terminaux
            if (longueur_cmd <= 5) {
                uint8_t tampon_tx[7]; // Tampon légèrement agrandi pour la sécurité
                tampon_tx[0] = 0xB2; // Identifiant réseau pour la config
                
                // On s'assure de ne pas envoyer plus de 4 lettres au capteur
                int taille_utile = (longueur_cmd > 4) ? 4 : longueur_cmd;
                
                // Copie des caractères de commande
                memcpy(&tampon_tx[1], instruction.toCharArray(), taille_utile);
                
                // Envoi de la trame radio au Micro:bit capteur (ID + lettres utiles)
                uBit.radio.datagram.send(tampon_tx, taille_utile + 1);
                
                // Signal ACK renvoyé au serveur Python
                uBit.serial.printf("ACK: %s\r\n", (char*)instruction.toCharArray());
                
                // Animation LED : affiche brièvement la première lettre
                uBit.display.print(instruction.charAt(0));
                uBit.sleep(250);
                uBit.display.clear();
            } else {
                uBit.serial.printf("{\"err\":\"Instruction trop longue\"}\r\n");
            }
        }
        
        uBit.sleep(20); 
    }
    
    release_fiber();
}