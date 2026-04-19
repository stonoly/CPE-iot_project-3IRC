#include "MicroBit.h"
#include "./drivers/ssd1306.h"
#include "./drivers/bme280.h"
#include "./drivers/tsl256x.h" // N'oublie pas d'inclure la librairie pour la luminosité !

MicroBit uBit;
MicroBitI2C bus_i2c(MICROBIT_PIN_P20, MICROBIT_PIN_P19);
MicroBitPin broche_P0(MICROBIT_ID_IO_P0, MICROBIT_PIN_P0, PIN_CAPABILITY_DIGITAL_OUT);

// Pointeurs vers nos capteurs et l'écran
ssd1306* ecran_oled;
bme280* capteur_meteo;
tsl256x* capteur_lumiere;

// Configuration par défaut au démarrage
ManagedString mode_actif = "THLP"; 

// --- FONCTION DE SÉCURITÉ (identique à la passerelle) ---
uint8_t calculer_crc_trame(uint8_t* donnees, int longueur) {
    uint8_t crc_val = 0;
    for (int idx = 0; idx < longueur; idx++) {
        crc_val += donnees[idx];
    }
    return crc_val;
}

// --- RÉCEPTION DES ORDRES D'AFFICHAGE ---
void reception_nouvel_ordre(MicroBitEvent) {
    uint8_t tampon_rx[32];
    int taille_reçue = uBit.radio.datagram.recv(tampon_rx, 32);

    // On vérifie que le message vient bien de la passerelle (identifiant 0xB2 pour la config)
    if (taille_reçue >= 2 && tampon_rx[0] == 0xB2) {
        char nouvel_ordre[5] = {0}; // Prévu pour 4 lettres max + le caractère de fin de chaîne
        int nb_lettres = taille_reçue - 1; 
        
        if(nb_lettres > 4) nb_lettres = 4; // Sécurité anti-débordement

        // Extraction dynamique des lettres reçues
        for(int j = 0; j < nb_lettres; j++) {
            nouvel_ordre[j] = (char)tampon_rx[j + 1];
        }
        
        mode_actif = ManagedString(nouvel_ordre);
    }
}

// --- BOUCLE PRINCIPALE ---
int main() {
    uBit.init();
    uBit.radio.enable();
    uBit.radio.setGroup(77); // Doit être identique à la passerelle

    // Initialisation des modules externes
    ecran_oled = new ssd1306(&uBit, &bus_i2c, &broche_P0);
    capteur_meteo = new bme280(&uBit, &bus_i2c);
    capteur_lumiere = new tsl256x(&uBit, &bus_i2c, TSL256x_ADDR, TSL256x_PACKAGE_T, TSL256x_LOW_GAIN, TSL256x_INTEGRATION_100ms);

    // Mise en écoute de la radio
    uBit.messageBus.listen(MICROBIT_ID_RADIO, MICROBIT_RADIO_EVT_DATAGRAM, reception_nouvel_ordre);

    // Petit message de démarrage personnalisé
    ecran_oled->clear();
    ecran_oled->display_line(0, 0, "SYSTEME ACTIF");
    ecran_oled->update_screen();
    uBit.sleep(1000);

    while (true) {
        // 1. LECTURE BRUTE DES CAPTEURS
        uint32_t press_brute = 0;
        int32_t temp_brute = 0;
        uint16_t hum_brute = 0;
        capteur_meteo->sensor_read(&press_brute, &temp_brute, &hum_brute);

        // 2. COMPENSATION POUR ENVOI RADIO
        int32_t val_t = capteur_meteo->compensate_temperature(temp_brute);
        uint16_t val_h = capteur_meteo->compensate_humidity(hum_brute);
        uint32_t val_p = capteur_meteo->compensate_pressure(press_brute);

        // Luminosité (directement exploitable)
        uint32_t val_l = 0;
        capteur_lumiere->sensor_read(NULL, NULL, &val_l);

        // 3. AFFICHAGE OLED (valeurs divisées par 100 pour la lisibilité)
        int t_ecran = val_t / 100;
        int h_ecran = val_h / 100;
        int p_ecran = val_p / 100;

        ecran_oled->clear();
        ManagedString entete = ManagedString("AFFICHAGE: ") + mode_actif;
        ecran_oled->display_line(0, 0, (char*)entete.toCharArray());

        int ligne = 1;
        // Parcours de la chaîne d'ordre pour afficher les capteurs dans le bon ordre
        for (int k = 0; k < mode_actif.length(); k++) {
            char commande = mode_actif.charAt(k);
            
            if (commande == 'T') {
                ManagedString txt = ManagedString("Temp: ") + ManagedString(t_ecran) + " C";
                ecran_oled->display_line(ligne++, 0, (char*)txt.toCharArray());
            } 
            else if (commande == 'H') {
                ManagedString txt = ManagedString("Humidite: ") + ManagedString(h_ecran) + " %";
                ecran_oled->display_line(ligne++, 0, (char*)txt.toCharArray());
            } 
            else if (commande == 'P') {
                ManagedString txt = ManagedString("Press: ") + ManagedString(p_ecran) + " hPa";
                ecran_oled->display_line(ligne++, 0, (char*)txt.toCharArray());
            } 
            else if (commande == 'L') {
                ManagedString txt = ManagedString("Lum: ") + ManagedString((int)val_l) + " lux";
                ecran_oled->display_line(ligne++, 0, (char*)txt.toCharArray());
            }
        }
        ecran_oled->update_screen();

        // 4. CONSTRUCTION ET ENVOI DE LA TRAME RADIO
        uint8_t trame_tx[17];
        trame_tx[0] = 0xA1; // ID d'envoi de mesures (attendu par la passerelle)
        trame_tx[1] = 0x01; // Version de la trame

        // Injection des valeurs brutes dans le tableau d'octets
        memcpy(&trame_tx[2], &val_t, 4);
        memcpy(&trame_tx[6], &val_h, 2);
        memcpy(&trame_tx[8], &val_p, 4);
        memcpy(&trame_tx[12], &val_l, 4);

        // Ajout du bit de parité à la toute fin
        trame_tx[16] = calculer_crc_trame(trame_tx, 16);

        uBit.radio.datagram.send(trame_tx, 17);

        // Pause de 2 secondes avant la prochaine lecture
        uBit.sleep(2000); 
    }

    release_fiber();
}