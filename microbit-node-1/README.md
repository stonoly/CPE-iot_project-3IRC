# Micro:bit Capteur — Node 1

Firmware du micro:bit capteur. Il lit les données environnementales toutes les 5 secondes, les chiffre et les envoie par radio à la passerelle. Il peut aussi recevoir une commande de config pour changer l'ordre d'affichage sur son écran OLED.

---

## Ce que fait ce code

- Lit la température, l'humidité et la pression via le **BME280** (I2C)
- Lit la luminosité via le **TSL256x** (I2C)
- Chiffre les données avec XORSHIFT32 + `CLE_RADIO` et les envoie par radio à la passerelle
- Reçoit les commandes de config depuis la passerelle (ex: `TLH`) et met à jour l'affichage OLED
- Affiche les valeurs sur l'écran **SSD1306** dans l'ordre configuré

> Pour ajouter un deuxième capteur, dupliquer ce firmware et changer `#define NUM_CAPTEUR 1` en `2`. Le reste du code n'a pas à être modifié.

---

## Sécurité

Chaque trame envoyée est chiffrée avec XORSHIFT32 initialisé depuis `CLE_RADIO` et le nonce courant. Le nonce est tiré aléatoirement au démarrage et incrémenté à chaque envoi — une trame capturée ne peut pas être réutilisée (anti-rejeu). Le CRC16 permet à la passerelle de rejeter les trames corrompues avant déchiffrement.

---

## Compilation et flash

```bash
# Depuis le dossier microbit-samples/
yt build

# Copier le .hex sur le micro:bit (Linux)
cp build/bbc-microbit-classic-gcc/source/microbit-samples-combined.hex /mnt/Microbit

# Windows : glisser-déposer le .hex sur le lecteur MICROBIT
```

Le micro:bit affiche `OBJ1` au démarrage, puis `IoT Objet / OBJ1 / Pret` sur l'OLED.

---

## Connexions matérielles

| Capteur | Bus | Adresse I2C |
|---------|-----|-------------|
| BME280 (T, H, P) | I2C — P20=SDA, P19=SCL | 0xEC |
| TSL256x (luminosité) | I2C — même bus | 0x52 |
| SSD1306 (OLED) | I2C — même bus + reset P0 | 0x7A |

---

## Config d'affichage OLED

La passerelle peut envoyer une commande pour changer l'ordre des valeurs affichées. Les lettres disponibles sont `T` (température), `L` (luminosité), `H` (humidité), `P` (pression).

Exemple : envoyer `TLH` affiche température, luminosité puis humidité, dans cet ordre.