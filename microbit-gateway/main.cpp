/*
 * ============================================================
 * MICRO:BIT PASSERELLE (GW) — Mini Projet IoT 2026
 * ============================================================
 *
 * RADIO (réception depuis capteur) :
 *   - PRNG XORSHIFT32 + CLE_RADIO
 *   - CRC16
 *   - Anti-rejeu nonce 2 octets
 *
 * Format trame radio reçue (21 octets) :
 *   [0]      = 0xA1           identifiant réseau
 *   [1..2]   = nonce          uint16_t little-endian
 *   [3..18]  = payload XORé   16 octets :
 *                [0]          = num_capteur  uint8_t
 *                [1..4]       = temp         int32_t  (0.01 °C)
 *                [5..6]       = hum          uint16_t (0.01 %rH)
 *                [7..10]      = press        uint32_t (hPa)
 *                [11..14]     = lum          uint32_t (lux)
 *                [15]         = padding      0x00
 *   [19..20] = CRC16          sur les 19 premiers octets
 *
 * UART (envoi vers serveur Python) :
 *   - PRNG XORSHIFT32 + CLE_UART
 *   - CRC16
 *   - Nonce UART initialisé aléatoirement
 *
 * Format trame UART envoyée :
 *   [0]      = 0xC3
 *   [1..2]   = nonce UART     uint16_t
 *   [3]      = taille payload
 *   [4..N]   = payload JSON chiffré
 *   [N+1..N+2] = CRC16
 *
 * Format trame radio envoyée (config affichage) :
 *   [0]    = 0xB2
 *   [1..2] = nonce_cfg        uint16_t
 *   [3..N] = payload XORé     lettres de config
 * ============================================================
 */

#include "MicroBit.h"
#include <cstdio>

MicroBit uBit;

// ============================================================
// CONFIG
// ============================================================
#define RADIO_GROUP 77

// ============================================================
// CLÉS
// ============================================================
static const uint8_t CLE_RADIO[8] = {
    0x49, 0x6F, 0x54, 0x32,
    0x30, 0x32, 0x36, 0x21   // "IoT2026!"
};

static const uint8_t CLE_UART[8] = {
    0x55, 0x41, 0x52, 0x54,
    0x32, 0x30, 0x32, 0x36   // "UART2026"
};

// ============================================================
// PRNG XORSHIFT32
// ============================================================
static uint32_t etat_prng = 0;

void initialiser_prng(const uint8_t* cle, uint16_t nonce) {
    etat_prng =
        ((uint32_t)cle[0] << 24) ^
        ((uint32_t)cle[1] << 16) ^
        ((uint32_t)cle[2] << 8 ) ^
        ((uint32_t)cle[3]);

    etat_prng ^= ((uint32_t)nonce << 16) | nonce;

    if (etat_prng == 0) {
        etat_prng = 0xA5A5A5A5;
    }
}

uint32_t xorshift32() {
    uint32_t x = etat_prng;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    etat_prng = x;
    return x;
}

// ============================================================
// CRC16
// ============================================================
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

// ============================================================
// NONCE UART
// ============================================================
static uint16_t nonce_uart = 0;

// ============================================================
// ENVOI UART CHIFFRÉ
// JSON : {"id":1,"t":2502,"h":4267,"p":995,"l":50}
// ============================================================
void envoyer_uart_chiffre(
    uint8_t  num_capteur,
    int32_t  t,
    uint16_t h,
    uint32_t p,
    uint32_t l
) {
    // Construction JSON avec num_capteur
    char json[96];
    snprintf(
        json, sizeof(json),
        "{\"id\":%u,\"t\":%ld,\"h\":%u,\"p\":%lu,\"l\":%lu}",
        (unsigned)num_capteur,
        (long)t,
        h,
        (unsigned long)p,
        (unsigned long)l
    );

    uint8_t taille_payload = strlen(json);

    // Construction trame UART
    uint8_t trame[128];
    trame[0] = 0xC3;
    memcpy(&trame[1], &nonce_uart, 2);
    trame[3] = taille_payload;

    // Chiffrement XORSHIFT32 avec CLE_UART
    initialiser_prng(CLE_UART, nonce_uart);
    for (int i = 0; i < taille_payload; i++) {
        uint8_t masque = (uint8_t)(xorshift32() & 0xFF);
        trame[4 + i] = ((uint8_t)json[i]) ^ masque;
    }

    // CRC16
    uint16_t crc = calculer_crc16(trame, 4 + taille_payload);
    memcpy(&trame[4 + taille_payload], &crc, 2);

    int taille_totale = 4 + taille_payload + 2;

    // Envoi UART binaire
    uBit.serial.send((uint8_t*)trame, taille_totale);

    nonce_uart++;
}

// ============================================================
// RÉCEPTION RADIO DEPUIS LE CAPTEUR
// ============================================================
void reception_trame_radio(MicroBitEvent) {
    uint8_t tampon_rx[32];
    int octets_recus = uBit.radio.datagram.recv(tampon_rx, 32);

    // Vérification taille (21 octets) et identifiant
    if (octets_recus != 21 || tampon_rx[0] != 0xA1) {
        return;
    }

    // --- Vérification CRC16 (sur les 19 premiers octets) ---
    uint16_t crc_recu;
    memcpy(&crc_recu, &tampon_rx[19], 2);

    uint16_t crc_calcule = calculer_crc16(tampon_rx, 19);
    if (crc_calcule != crc_recu) {
        uBit.display.print("C");
        return;
    }

    // --- Vérification anti-rejeu (nonce 2 octets) ---
    uint16_t nonce_recu;
    memcpy(&nonce_recu, &tampon_rx[1], 2);

    static uint16_t dernier_nonce = 0;
    static bool premier_paquet    = true;

    uint16_t diff = nonce_recu - dernier_nonce;
    if (!premier_paquet && diff == 0) {
        uBit.display.print("R");
        return;
    }
    premier_paquet = false;
    dernier_nonce  = nonce_recu;

    // --- Affichage trame radio chiffrée (hex) pour démonstration ---
    uBit.serial.printf("radio_chiffre: ");
    for (int i = 3; i < 19; i++) {
        uBit.serial.printf("%02X ", tampon_rx[i]);
    }
    uBit.serial.printf("\r\n");

    // --- Déchiffrement XORSHIFT32 du payload radio ---
    uint8_t payload[16];
    initialiser_prng(CLE_RADIO, nonce_recu);
    for (int i = 0; i < 16; i++) {
        uint8_t masque = (uint8_t)(xorshift32() & 0xFF);
        payload[i] = tampon_rx[3 + i] ^ masque;
    }

    // --- Extraction des valeurs ---
    uint8_t  num_capteur = payload[0];
    int32_t  val_temp;
    uint16_t val_hum;
    uint32_t val_press;
    uint32_t val_lum;

    memcpy(&val_temp,  &payload[1],  4);
    memcpy(&val_hum,   &payload[5],  2);
    memcpy(&val_press, &payload[7],  4);
    memcpy(&val_lum,   &payload[11], 4);

    // --- Envoi UART chiffré vers le serveur Python ---
    envoyer_uart_chiffre(num_capteur, val_temp, val_hum, val_press, val_lum);

    // Feedback LED
    uBit.display.image.setPixelValue(2, 2, 255);
    uBit.sleep(50);
    uBit.display.image.setPixelValue(2, 2, 0);
}

// ============================================================
// MAIN
// ============================================================
int main() {
    uBit.init();

    // Nonce UART initialisé aléatoirement
    nonce_uart = uBit.random(65535);

    // Radio
    uBit.radio.enable();
    uBit.radio.setGroup(RADIO_GROUP);
    uBit.messageBus.listen(
        MICROBIT_ID_RADIO,
        MICROBIT_RADIO_EVT_DATAGRAM,
        reception_trame_radio
    );

    uBit.display.scroll("GW SEC");

    while (true) {
        // Réception commandes Python (config affichage)
        ManagedString instruction = uBit.serial.readUntil("\r\n");

        if (instruction.length() > 0) {
            int longueur_cmd = instruction.length();

            if (longueur_cmd <= 5) {
                int taille_utile = (longueur_cmd > 4) ? 4 : longueur_cmd;

                // Trame config : [0xB2][nonce_cfg 2o][payload XORé]
                uint8_t tampon_tx[16];
                tampon_tx[0] = 0xB2;

                uint16_t nonce_cfg = uBit.random(65535);
                memcpy(&tampon_tx[1], &nonce_cfg, 2);

                const char* lettres = instruction.toCharArray();

                // Chiffrement XORSHIFT32 avec CLE_RADIO
                initialiser_prng(CLE_RADIO, nonce_cfg);
                for (int i = 0; i < taille_utile; i++) {
                    uint8_t masque = (uint8_t)(xorshift32() & 0xFF);
                    tampon_tx[3 + i] = ((uint8_t)lettres[i]) ^ masque;
                }

                uBit.radio.datagram.send(tampon_tx, taille_utile + 3);

                uBit.display.print(instruction.charAt(0));
                uBit.sleep(100);
                uBit.display.clear();
            }
        }

        uBit.sleep(20);
    }

    release_fiber();
    return 0;
}