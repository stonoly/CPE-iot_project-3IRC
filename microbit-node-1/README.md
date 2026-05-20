# Objet capteur micro:bit — Mini Architecture IoT

Firmware embarqué de **l'objet capteur** (n° 1) développé dans le cadre du mini-projet
**Développement embarqué et IoT** (CPE Lyon, 3IRC).

Cette micro:bit, déployée « dans un bureau », mesure les conditions ambiantes (température, humidité,
pression, luminosité), les envoie en radio 2.4 GHz à la passerelle, et affiche les valeurs sur un écran
OLED dans l'ordre demandé par l'utilisateur.

---

## 1. Contexte du projet

L'architecture globale du projet est la suivante :

```
[micro:bit capteur]  --RF 2.4GHz-->  [micro:bit passerelle (USB)]  <--UART-->  [Serveur (PC)]  <--UDP/WiFi-->  [Application Android]
 ^^^^^^^^^^^^^^^^^
 (ce dossier)
```

- **L'objet capteur** (ce dossier) lit ses capteurs toutes les 5 s, sérialise les mesures, les chiffre puis
  les envoie en radio à la passerelle.
- La passerelle (`microbit-gateway/`) relaie les données vers le serveur.
- En retour, l'objet écoute la radio pour recevoir une **commande de configuration d'affichage** (par
  exemple `TLH` → Température puis Luminosité puis Humidité sur l'OLED) émise depuis l'application Android.

---

## 2. Fonctionnalités

Le firmware répond aux besoins listés dans le sujet pour la partie « objet » :

| Fonctionnalité                              | Description                                                                                              |
| ------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| Mesure des capteurs                         | Lecture périodique du BME280 (T, H, P) et du TSL256x (luminosité) via le bus I²C.                        |
| Émission radio sécurisée                    | Sérialisation des mesures + chiffrement **XORSHIFT32** + **CRC16** + **nonce anti-rejeu** (toutes les 5 s).|
| Réception radio de la configuration         | Écoute du groupe radio `77`, déchiffrement et validation des lettres reçues (`T`, `L`, `H`, `P`).        |
| Affichage OLED                              | Mise à jour de l'écran SSD1306 dans l'**ordre demandé** par la dernière commande reçue.                  |
| Identification de l'objet                   | Constante `NUM_CAPTEUR` embarquée dans chaque trame radio pour distinguer les objets d'un même réseau.   |

---

## 3. Interface utilisateur (sur l'objet)

L'objet expose deux surfaces d'affichage :

1. **Matrice LED 5×5** intégrée à la micro:bit :
   - Au démarrage, défilement de `"OBJ1"`.
   - Un pixel central qui clignote à chaque émission radio (preuve de vie).
   - Un pixel en `(4, 4)` qui clignote à chaque réception d'une commande de configuration valide.
2. **Écran OLED SSD1306 128×64 (I²C)** : affichage des mesures formatées (`T:`, `L:`, `H:`, `P:`) dans
   l'ordre défini par la chaîne `displayConfig` (par défaut `TLHP`).

---

## 4. Architecture du code

Comme la passerelle, l'objet est concentré dans **un seul fichier `main.cpp`** ; les drivers I²C sont
isolés dans le sous-dossier `drivers/`.

```
microbit-node-1/
├── main.cpp                  # Firmware de l'objet (capteurs + radio + OLED)
└── drivers/
    ├── bme280.{cpp,h}        # Driver BME280 (température / humidité / pression)
    ├── tsl256x.{cpp,h}       # Driver TSL256x (luminosité)
    ├── ssd1306.{cpp,h}       # Driver SSD1306 (écran OLED)
    └── font.h                # Police bitmap utilisée par le SSD1306
```

### Points techniques notables (`main.cpp`)

- **Lecture des capteurs** : `bme.sensor_read()` puis compensation logicielle (`compensate_temperature`,
  `compensate_pressure`, `compensate_humidity`) pour obtenir des unités physiques (0.01 °C, hPa, 0.01 %rH) ;
  `tsl.sensor_read()` pour la luminosité en lux.
- **PRNG XORSHIFT32** (`initialiser_prng` / `xorshift32`) : générateur pseudo-aléatoire identique à celui
  de la passerelle ; il est réinitialisé à chaque message à partir de `CLE_RADIO` et du nonce, ce qui assure
  que les deux extrémités produisent la même séquence de masques.
- **CRC16** (`calculer_crc16`) : polynôme `0xA001`, calculé sur les 19 premiers octets de la trame.
- **Anti-rejeu** : `nonce` 16 bits initialisé aléatoirement au démarrage (`uBit.random(65535)`), puis
  incrémenté à chaque envoi. La passerelle s'en sert pour rejeter les paquets dupliqués.
- **Réception config** (`onRadioReceive`) : déchiffrement, validation que toutes les lettres appartiennent à
  l'ensemble `{T, L, H, P}` avant d'écraser `displayConfig`. En cas de lettre invalide, la commande est
  **silencieusement ignorée**.
- **Boucle principale** : cycle de 5 secondes (`SEND_INTERVAL = 5000`) : mesure → envoi radio → mise à jour
  OLED → sleep.

---

## 5. Protocoles de communication

### 5.1 Trame radio envoyée (objet → passerelle) — 21 octets

| Offset      | Taille | Champ              | Description                                                    |
| ----------- | ------ | ------------------ | -------------------------------------------------------------- |
| `[0]`       | 1      | Identifiant réseau | Toujours `0xA1`.                                               |
| `[1..2]`    | 2      | Nonce              | `uint16_t` little-endian, incrémenté à chaque émission.        |
| `[3..18]`   | 16     | Payload chiffré    | XOR-é avec `CLE_RADIO` + nonce. Contient les mesures capteur.  |
| `[19..20]`  | 2      | CRC16              | Calculé sur les 19 octets précédents.                          |

**Payload brut (avant chiffrement, 16 octets)** :

| Offset    | Taille | Champ        | Format / Unité                                      |
| --------- | ------ | ------------ | --------------------------------------------------- |
| `[0]`     | 1      | `num_capteur`| Identifiant unique de l'objet (ici `NUM_CAPTEUR=1`).|
| `[1..4]`  | 4      | `temp`       | Température en 0.01 °C (`int32_t`).                 |
| `[5..6]`  | 2      | `hum`        | Humidité relative en 0.01 %rH (`uint16_t`).         |
| `[7..10]` | 4      | `press`      | Pression en hPa (`uint32_t`).                       |
| `[11..14]`| 4      | `lum`        | Luminosité en lux (`uint32_t`).                     |
| `[15]`    | 1      | padding      | Réservé, vaut `0x00`.                               |

### 5.2 Trame radio reçue (passerelle → objet, config affichage)

| Offset     | Taille | Champ            | Description                                                   |
| ---------- | ------ | ---------------- | ------------------------------------------------------------- |
| `[0]`      | 1      | Identifiant      | Toujours `0xB2`.                                              |
| `[1..2]`   | 2      | `nonce_cfg`      | Nonce 16 bits aléatoire (généré côté passerelle).             |
| `[3..N+2]` | N      | Payload chiffré  | Lettres de configuration (1 à 7), XOR-ées avec `CLE_RADIO`.   |

Lettres acceptées (toute lettre hors de cet ensemble fait rejeter le paquet) :

- `T` — Température
- `L` — Luminosité
- `H` — Humidité
- `P` — Pression

Exemples valides : `T`, `TL`, `TLH`, `TLHP`, `PHLT`, ...

---

## 6. Connexions matérielles

Tous les périphériques sont sur le **même bus I²C** de la micro:bit (`P20 = SDA`, `P19 = SCL`).

| Périphérique | Adresse I²C | Broche supplémentaire | Rôle                                   |
| ------------ | ----------- | --------------------- | -------------------------------------- |
| BME280       | `0xEC`      | —                     | Capteur Température / Humidité / Pression. |
| TSL256x      | `0x52`      | —                     | Capteur de luminosité.                 |
| SSD1306      | `0x7A`      | `P0` (reset)          | Écran OLED 128×64 d'affichage.         |

> Le schéma de câblage (carte d'extension I²C + capteurs) est celui fourni par l'école pour les TPs ; aucun
> branchement supplémentaire n'est nécessaire.

---

## 7. Prérequis

- Une carte **BBC micro:bit V2** équipée :
  - du module capteur **BME280**,
  - du module capteur **TSL256x**,
  - de l'écran OLED **SSD1306** (128×64 I²C).
- L'environnement de build **Yotta** ou le projet template
  [`microbit-v2-samples`](https://github.com/lancaster-university/microbit-v2-samples) de Lancaster University.
- Un câble **USB** pour le flashage et le monitoring série (debug).
- Une passerelle micro:bit flashée avec le firmware de `microbit-gateway/` configurée sur le **même groupe
  radio** (`77`) et la **même clé** (`CLE_RADIO`).

---

## 8. Compilation et flashage

Le projet est conçu pour s'intégrer dans le squelette `microbit-v2-samples` (CODAL).
La procédure typique consiste à :

1. Cloner le template :
   ```bash
   git clone https://github.com/lancaster-university/microbit-v2-samples.git
   cd microbit-v2-samples
   ```
2. Copier le contenu de ce dossier `microbit-node-1/` à la racine du template (le `main.cpp` remplace celui
   fourni par défaut, le sous-dossier `drivers/` est ajouté à l'arborescence de sources).
3. Compiler le firmware :
   ```bash
   python build.py
   ```
4. Récupérer le binaire `MICROBIT.hex` généré dans `MICROBIT/` et le glisser-déposer sur le lecteur USB
   `MICROBIT` exposé par la carte.

---

## 9. Utilisation

1. Flasher la passerelle (cf. `microbit-gateway/README.md`) puis l'objet capteur.
2. Mettre l'objet sous tension (USB ou batterie). Au démarrage :
   - la matrice LED fait défiler `"OBJ1"`,
   - l'OLED affiche `IoT Objet / OBJ1 / Pret`.
3. Toutes les 5 secondes, l'objet :
   - lit ses capteurs,
   - envoie une trame radio chiffrée (pixel central qui clignote),
   - met à jour l'écran OLED dans l'ordre défini par `displayConfig` (par défaut `TLHP`).
4. Depuis l'application Android, envoyer une commande de configuration (par exemple `TLH`).
   Lorsque l'objet la reçoit et la valide, le pixel `(4, 4)` clignote brièvement et l'OLED est réorganisé
   au cycle suivant.

---

## 10. Configuration

Les principaux paramètres se trouvent en tête de `main.cpp` :

```cpp
#define RADIO_GROUP    77
#define OBJECT_ID      "OBJ1"
#define NUM_CAPTEUR    1        // numéro unique de ce capteur
#define SEND_INTERVAL  5000     // ms entre deux envois

static const uint8_t CLE_RADIO[8] = { ... };   // "IoT2026!"
```

Pour déployer un **second objet** dans un autre bureau :

1. Cloner ce dossier (par exemple en `microbit-node-2/`).
2. Modifier `NUM_CAPTEUR` (passer à `2`, `3`, ...) et éventuellement `OBJECT_ID` (`"OBJ2"`, ...).
3. **Conserver le même `RADIO_GROUP` et la même `CLE_RADIO`** pour rester compatible avec la passerelle.
4. Compiler et flasher la nouvelle carte.

La passerelle et le serveur Python distinguent ensuite les objets grâce au champ `"id"` du JSON
(`{"id":1,...}`, `{"id":2,...}`, ...).
