/*
 * Micro:bit OBJET — Mini Projet IoT 2026
 * ========================================
 * Rôle :
 *   1. Lire les données BME280 (T, H, P) et TSL256x (L) toutes les 5 s
 *   2. Envoyer "T:24,L:312,H:58,P:1012" par radio au micro:bit passerelle
 *   3. Recevoir "OBJ1:TLH" depuis la passerelle (config d'affichage)
 *   4. Afficher les données sur l'écran OLED SSD1306 dans l'ordre demandé
 *
 * Protocole radio (groupe 42) :
 *   Envoi     : "T:<°C>,L:<lux>,H:<%>,P:<hPa>"
 *   Réception : "OBJ1:<config>"  ex: "OBJ1:TLH"
 *
 * Connexions matérielles :
 *   BME280  : I2C (P20=SDA, P19=SCL), adresse 0xEC
 *   TSL256x : I2C (même bus),          adresse 0x52
 *   SSD1306 : I2C (même bus) + reset sur P0, adresse 0x7A
 *
 * Compilation (yotta, depuis microbit-samples/) :
 *   yt build
 *   cp build/bbc-microbit-classic-gcc/source/microbit-samples-combined.hex /mnt/Microbit
 *
 * IMPORTANT : Ce fichier est le firmware de l'OBJET (capteurs + OLED).
 * Pour le firmware de la PASSERELLE (micro:bit branché au PC),
 * remplacer ce fichier par le contenu de ../source/main.cpp (racine du projet)
 * avant de lancer yt build.
 */

#include "MicroBit.h"
#include "drivers/bme280.h"
#include "drivers/tsl256x.h"
#include "drivers/ssd1306.h"
#include <cstdio>

MicroBit     uBit;
MicroBitI2C  i2c(I2C_SDA0, I2C_SCL0);
MicroBitPin  resetPin(MICROBIT_ID_IO_P0, MICROBIT_PIN_P0, PIN_CAPABILITY_DIGITAL_OUT);

#define RADIO_GROUP    42
#define OBJECT_ID      "OBJ1"
#define SEND_INTERVAL  5000   // ms entre deux envois de données

// Configuration d'affichage courante (ordre des capteurs à afficher)
// Chaque caractère est une lettre capteur valide : T, L, H, P
char displayConfig[8] = "TLHP";

// Dernières valeurs capteurs — mises à jour dans la boucle principale
int      g_temp = 0;    // en 0.01 °C   (bme.compensate_temperature)
uint32_t g_lux  = 0;    // en lux       (tsl.sensor_read)
uint32_t g_hum  = 0;    // en 0.01 %rH  (bme.compensate_humidity)
uint32_t g_pres = 0;    // en hPa       (bme.compensate_pressure / 100)


// =========================================================================
// Callback radio : réception d'une config depuis la passerelle
// Format attendu : "OBJ1:TLH"
// =========================================================================
void onRadioReceive(MicroBitEvent)
{
    ManagedString msg = uBit.radio.datagram.recv();

    // Vérifier le préfixe "OBJ1:"
    const char* prefix    = OBJECT_ID ":";
    const int   prefixLen = 5;   // strlen("OBJ1:") == 5

    if (msg.length() <= prefixLen)
        return;

    for (int i = 0; i < prefixLen; i++) {
        if (msg.charAt(i) != prefix[i])
            return;
    }

    // Extraire la config (ex: "TLH")
    ManagedString cfg = msg.substring(prefixLen, msg.length() - prefixLen);
    int len = cfg.length();
    if (len < 1 || len > 7)
        return;

    for (int i = 0; i < len; i++)
        displayConfig[i] = cfg.charAt(i);
    displayConfig[len] = '\0';

    // Feedback visuel : pixel coin bas-droite pendant 150 ms
    uBit.display.image.setPixelValue(4, 4, 255);
    uBit.sleep(150);
    uBit.display.image.setPixelValue(4, 4, 0);
}


// =========================================================================
// Mise à jour de l'écran OLED selon displayConfig
// =========================================================================
void updateOLED(ssd1306& screen)
{
    screen.clear();
    char buf[17];   // 16 caractères max par ligne + '\0'
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
// MAIN
// =========================================================================
int main()
{
    uBit.init();

    // Radio — même groupe que la passerelle
    uBit.radio.enable();
    uBit.radio.setGroup(RADIO_GROUP);
    uBit.messageBus.listen(MICROBIT_ID_RADIO, MICROBIT_RADIO_EVT_DATAGRAM,
                           onRadioReceive);

    // Capteurs (sur le même bus I2C)
    bme280  bme(&uBit, &i2c);
    tsl256x tsl(&uBit, &i2c);

    // Écran OLED (reset sur P0)
    ssd1306 screen(&uBit, &i2c, &resetPin);

    // Message de démarrage sur la matrice LED et l'OLED
    uBit.display.scroll("OBJ1");
    screen.display_line(0, 0, "IoT Objet");
    screen.display_line(1, 0, OBJECT_ID);
    screen.display_line(2, 0, "Pret");
    screen.update_screen();
    uBit.sleep(2000);

    while (true) {
        // 1. Lecture BME280 (température, humidité, pression)
        uint32_t rawPres = 0;
        int32_t  rawTemp = 0;
        uint16_t rawHum  = 0;
        bme.sensor_read(&rawPres, &rawTemp, &rawHum);

        g_temp = bme.compensate_temperature((int)rawTemp);     // 0.01 °C
        g_pres = bme.compensate_pressure((int)rawPres) / 100; // hPa
        g_hum  = bme.compensate_humidity((int)rawHum);        // 0.01 %rH

        // 2. Lecture TSL256x (luminosité)
        uint16_t comb = 0, ir = 0;
        tsl.sensor_read(&comb, &ir, &g_lux);

        // 3. Envoi radio vers la passerelle
        // Format : "T:24,L:312,H:58,P:1012"
        ManagedString radioMsg =
            ManagedString("T:")  + ManagedString(g_temp / 100)       +
            ManagedString(",L:") + ManagedString((int)g_lux)         +
            ManagedString(",H:") + ManagedString((int)(g_hum / 100)) +
            ManagedString(",P:") + ManagedString((int)g_pres);

        uBit.radio.datagram.send(radioMsg);

        // Feedback LED central : allumé pendant la mise à jour OLED
        uBit.display.image.setPixelValue(2, 2, 255);

        // 4. Mise à jour de l'écran OLED
        updateOLED(screen);

        uBit.sleep(100);
        uBit.display.image.setPixelValue(2, 2, 0);

        // 5. Attente avant le prochain cycle
        uBit.sleep(SEND_INTERVAL - 100);
    }

    release_fiber();
    return 0;
}
