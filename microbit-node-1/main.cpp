/*
 * Micro:bit OBJET (capteurs) — Mini Projet IoT 2026
 * ===================================================
 * Rôle :
 *   1. Lire les données BME280 (T, H, P) et TSL256x (L) toutes les 5 s
 *   2. Chiffrer et envoyer la trame par radio à la passerelle
 *   3. Recevoir la config d'affichage (chiffrée) depuis la passerelle
 *   4. Afficher les données sur l'écran OLED SSD1306 dans l'ordre demandé
 *
 * Sécurité :
 *   - PRNG XORSHIFT32 initialisé avec CLE_RADIO + nonce
 *   - Nonce 2 octets (anti-rejeu, initialisé aléatoirement au démarrage)
 *   - CRC16 (intégrité de la trame)
 *
 * Format trame radio envoyée (21 octets) :
 *   [0]      = 0xA1           identifiant réseau
 *   [1..2]   = nonce          uint16_t little-endian
 *   [3..18]  = payload XORé   16 octets chiffrés :
 *                [0]          = num_capteur  uint8_t  (ex: 1)
 *                [1..4]       = temp         int32_t  (0.01 °C)
 *                [5..6]       = hum          uint16_t (0.01 %rH)
 *                [7..10]      = press        uint32_t (hPa)
 *                [11..14]     = lum          uint32_t (lux)
 *                [15]         = padding      0x00
 *   [19..20] = CRC16          sur les 19 premiers octets
 *
 * Format trame radio reçue (config affichage) :
 *   [0]    = 0xB2             identifiant réseau config
 *   [1..2] = nonce_cfg        uint16_t
 *   [3..N] = payload XORé     lettres de config (ex: "TLH")
 *
 * Connexions matérielles :
 *   BME280  : I2C (P20=SDA, P19=SCL), adresse 0xEC
 *   TSL256x : I2C (même bus),          adresse 0x52
 *   SSD1306 : I2C (même bus) + reset sur P0, adresse 0x7A
 */

#include "MicroBit.h"
#include "drivers/bme280.h"
#include "drivers/tsl256x.h"
#include "drivers/ssd1306.h"
#include <cstdio>

MicroBit     uBit;
MicroBitI2C  i2c(I2C_SDA0, I2C_SCL0);
MicroBitPin  resetPin(MICROBIT_ID_IO_P0, MICROBIT_PIN_P0, PIN_CAPABILITY_DIGITAL_OUT);

#define RADIO_GROUP    77
#define OBJECT_ID      "OBJ1"
#define NUM_CAPTEUR    1        // ← numéro unique de ce capteur
#define SEND_INTERVAL  5000     // ms entre deux envois

static const uint8_t CLE_RADIO[8] = {
    0x49, 0x6F, 0x54, 0x32,
    0x30, 0x32, 0x36, 0x21   // "IoT2026!"
};

static uint16_t nonce      = 0;
static uint32_t etat_prng  = 0;

char displayConfig[8] = "TLHP";

int      g_temp = 0;    // en 0.01 °C
uint32_t g_lux  = 0;    // en lux
uint32_t g_hum  = 0;    // en 0.01 %rH
uint32_t g_pres = 0;    // en hPa


// =========================================================================
// Initialise le PRNG à partir des 4 premiers octets de CLE_RADIO
// et du nonce. Le nonce est mélangé deux fois pour que deux nonces
// proches ne produisent pas des flux trop similaires.
// =========================================================================
void initialiser_prng(uint16_t nonce_local) {
    etat_prng =
        ((uint32_t)CLE_RADIO[0] << 24) ^
        ((uint32_t)CLE_RADIO[1] << 16) ^
        ((uint32_t)CLE_RADIO[2] << 8 ) ^
        ((uint32_t)CLE_RADIO[3]);

    etat_prng ^= ((uint32_t)nonce_local << 16) | nonce_local;

    if (etat_prng == 0) {
        etat_prng = 0xA5A5A5A5;
    }
}

// =========================================================================
// Génère le prochain mot 32 bits du flux pseudo-aléatoire.
// On prend uniquement l'octet de poids faible comme masque de chiffrement.
// =========================================================================
uint32_t xorshift32() {
    uint32_t x = etat_prng;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    etat_prng = x;
    return x;
}

// =========================================================================
// CRC16 Modbus sur `taille` octets.
// Permet à la passerelle de détecter toute corruption de la trame
// avant même de tenter le déchiffrement.
// =========================================================================
uint16_t calculer_crc16(uint8_t* data, int taille) {
    uint16_t crc = 0xFFFF;
    for (int i = 0; i < taille; i++) {
        crc ^= data[i];
        for (int j = 0; j < 8; j++) {
            if (crc & 1)
                crc = (crc >> 1) ^ 0xA001;
            else
                crc >>= 1;
        }
    }
    return crc;
}

// =========================================================================
// Callback radio déclenché à la réception d'une trame de config (0xB2).
// Déchiffre les lettres avec le nonce embarqué dans la trame,
// valide qu'elles appartiennent à {T, L, H, P}, puis met à jour
// l'ordre d'affichage sur l'OLED.
// =========================================================================
void onRadioReceive(MicroBitEvent) {
    uint8_t tampon_rx[32];
    int octets_recus = uBit.radio.datagram.recv(tampon_rx, 32);

    if (octets_recus < 4 || tampon_rx[0] != 0xB2) {
        return;
    }

    uint16_t nonce_cfg;
    memcpy(&nonce_cfg, &tampon_rx[1], 2);

    int nb_lettres = octets_recus - 3;
    if (nb_lettres < 1 || nb_lettres > 7) {
        return;
    }

    char cfg_dechiffree[8];
    initialiser_prng(nonce_cfg);

    for (int i = 0; i < nb_lettres; i++) {
        uint8_t masque = (uint8_t)(xorshift32() & 0xFF);
        cfg_dechiffree[i] = (char)(tampon_rx[3 + i] ^ masque);
    }
    cfg_dechiffree[nb_lettres] = '\0';

    for (int i = 0; i < nb_lettres; i++) {
        char c = cfg_dechiffree[i];
        if (c != 'T' && c != 'L' && c != 'H' && c != 'P') {
            return;
        }
    }

    for (int i = 0; i <= nb_lettres; i++) {
        displayConfig[i] = cfg_dechiffree[i];
    }

    uBit.display.image.setPixelValue(4, 4, 255);
    uBit.sleep(150);
    uBit.display.image.setPixelValue(4, 4, 0);
}

// =========================================================================
// Rafraîchit l'écran OLED en affichant les capteurs dans l'ordre
// défini par displayConfig (ex: "TLH" → température, luminosité, humidité).
// =========================================================================
void updateOLED(ssd1306& screen) {
    screen.clear();
    char buf[20];
    int line = 0;

    for (int i = 0; displayConfig[i] != '\0' && line < 8; i++) {
        char c = displayConfig[i];

        if (c == 'T') {
            int t_int = g_temp / 100;
            int t_dec = (g_temp >= 0 ? g_temp : -g_temp) % 100;
            snprintf(buf, sizeof(buf), "T: %d.%02d C", t_int, t_dec);
        } else if (c == 'L') {
            snprintf(buf, sizeof(buf), "L: %d lux", (int)g_lux);
        } else if (c == 'H') {
            snprintf(buf, sizeof(buf), "H: %d %%", (int)(g_hum / 100));
        } else if (c == 'P') {
            snprintf(buf, sizeof(buf), "P: %d hPa", (int)g_pres);
        } else {
            continue;
        }

        screen.display_line(line, 0, buf);
        line++;
    }

    screen.update_screen();
}

// =========================================================================
// Sérialise les quatre valeurs capteurs + le numéro de capteur dans
// un payload de 16 octets, chiffre avec XORSHIFT32 + nonce courant,
// calcule le CRC16, puis envoie la trame de 21 octets par radio.
// Le nonce est incrémenté après chaque envoi.
// =========================================================================
void envoyer_trame_capteurs() {
    uint8_t trame[21];

    trame[0] = 0xA1;
    memcpy(&trame[1], &nonce, 2);

    uint8_t payload[16];
    int32_t  t = (int32_t)g_temp;
    uint16_t h = (uint16_t)(g_hum & 0xFFFF);
    uint32_t p = (uint32_t)g_pres;
    uint32_t l = (uint32_t)g_lux;

    payload[0]  = (uint8_t)NUM_CAPTEUR;
    memcpy(&payload[1],  &t, 4);
    memcpy(&payload[5],  &h, 2);
    memcpy(&payload[7],  &p, 4);
    memcpy(&payload[11], &l, 4);
    payload[15] = 0x00;

    initialiser_prng(nonce);
    for (int i = 0; i < 16; i++) {
        uint8_t masque = (uint8_t)(xorshift32() & 0xFF);
        trame[3 + i] = payload[i] ^ masque;
    }

    uint16_t crc = calculer_crc16(trame, 19);
    memcpy(&trame[19], &crc, 2);

    uBit.radio.datagram.send(trame, 21);

    nonce++;
}


// =========================================================================
// MAIN
// =========================================================================
int main() {
    uBit.init();

    nonce = uBit.random(65535);

    uBit.radio.enable();
    uBit.radio.setGroup(RADIO_GROUP);
    uBit.messageBus.listen(
        MICROBIT_ID_RADIO,
        MICROBIT_RADIO_EVT_DATAGRAM,
        onRadioReceive
    );

    bme280  bme(&uBit, &i2c);
    tsl256x tsl(&uBit, &i2c);
    ssd1306 screen(&uBit, &i2c, &resetPin);

    uBit.display.scroll("OBJ1");
    screen.display_line(0, 0, "IoT Objet");
    screen.display_line(1, 0, OBJECT_ID);
    screen.display_line(2, 0, "Pret");
    screen.update_screen();
    uBit.sleep(2000);

    while (true) {
        uint32_t rawPres = 0;
        int32_t  rawTemp = 0;
        uint16_t rawHum  = 0;
        bme.sensor_read(&rawPres, &rawTemp, &rawHum);

        g_temp = bme.compensate_temperature((int)rawTemp);
        g_pres = bme.compensate_pressure((int)rawPres) / 100;
        g_hum  = bme.compensate_humidity((int)rawHum);

        uint16_t comb = 0, ir = 0;
        tsl.sensor_read(&comb, &ir, &g_lux);

        envoyer_trame_capteurs();

        uBit.display.image.setPixelValue(2, 2, 255);
        updateOLED(screen);
        uBit.sleep(100);
        uBit.display.image.setPixelValue(2, 2, 0);

        uBit.sleep(SEND_INTERVAL - 100);
    }

    release_fiber();
    return 0;
}