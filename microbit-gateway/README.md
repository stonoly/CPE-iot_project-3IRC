# Passerelle micro:bit — Mini Architecture IoT

Firmware embarqué de la **passerelle micro:bit** développée dans le cadre du mini-projet
**Développement embarqué et IoT** (CPE Lyon, 3IRC).

Cette micro:bit, connectée au PC par USB, fait le lien entre :

- les **objets capteurs** (autres micro:bit déployés dans les bureaux) via la **radio 2.4 GHz**,
- le **serveur Python** (PC) via la **liaison série UART**.

---

## 1. Contexte du projet

L'architecture globale du projet est la suivante :

```
[micro:bit capteur]  --RF 2.4GHz-->  [micro:bit passerelle (USB)]  <--UART-->  [Serveur (PC)]  <--UDP/WiFi-->  [Application Android]
                                            ^^^^^^^^^^^^^^^
                                            (ce dossier)
```

- Le capteur (`microbit-node-1`) collecte les données (température, humidité, pression, luminosité) et les
  envoie en RF 2.4 GHz à la passerelle.
- **La passerelle** (ce dossier) reçoit ces trames radio, vérifie leur intégrité, les déchiffre, puis les
  retransmet au serveur en UART au format JSON chiffré.
- Le serveur peut également envoyer à la passerelle (via UART) la **configuration d'affichage OLED** demandée
  par l'application Android (ordre des données : `TLH`, `LTH`, ...). La passerelle se charge alors de chiffrer
  cette commande et de la diffuser en radio vers l'objet capteur.

---

## 2. Fonctionnalités

Le firmware répond aux besoins listés dans le sujet pour la partie « passerelle » :

| Fonctionnalité                                | Description                                                                                              |
| --------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| Réception radio des trames capteur            | Écoute du groupe radio `77` à 2.4 GHz, déclenchement sur l'évènement `MICROBIT_RADIO_EVT_DATAGRAM`.       |
| Contrôle d'intégrité                          | Validation d'un **CRC16** sur 19 octets ainsi que de l'identifiant réseau `0xA1`.                        |
| Anti-rejeu                                    | Vérification d'un **nonce 2 octets** (rejet des paquets dupliqués).                                      |
| Déchiffrement radio                           | XOR par flux **XORSHIFT32** réinitialisé avec une clé `CLE_RADIO` et le nonce reçu.                      |
| Émission UART vers le serveur                 | Construction d'un JSON `{"id":...,"t":...,"h":...,"p":...,"l":...}` puis envoi sous trame chiffrée.      |
| Réception UART depuis le serveur              | Lecture d'une commande texte courte (ex : `TLH`) sur l'UART.                                             |
| Émission radio de la configuration            | Chiffrement de la commande (XORSHIFT32 + nonce aléatoire) puis envoi à l'objet capteur via la radio.     |

---

## 3. Architecture du code

Le firmware est volontairement compact : **un seul fichier `main.cpp`** suffit à couvrir les besoins du sujet.
Le sous-dossier `drivers/` contient des drivers I²C (SSD1306, BME280, TSL256x) hérités du template fourni par
l'école ; ils **ne sont pas utilisés par la passerelle** (qui n'embarque aucun capteur ni écran) mais sont
conservés pour rester cohérent avec le projet de l'objet capteur.

```
microbit-gateway/
├── main.cpp                  # Firmware de la passerelle (radio + UART + crypto)
└── drivers/                  # Drivers I²C hérités du template (non utilisés ici)
    ├── bme280.{cpp,h}        # Driver BME280 (température / humidité / pression)
    ├── tsl256x.{cpp,h}       # Driver TSL256x (luminosité)
    ├── ssd1306.{cpp,h}       # Driver SSD1306 (écran OLED)
    └── font.h                # Police bitmap utilisée par le SSD1306
```

### Points techniques notables (`main.cpp`)

- **PRNG XORSHIFT32** (`initialiser_prng` / `xorshift32`) : générateur pseudo-aléatoire utilisé pour produire
  un flux de masques XOR. Il est réinitialisé à chaque message à partir d'une clé (`CLE_RADIO` ou `CLE_UART`)
  et du nonce du paquet, ce qui assure qu'émetteur et récepteur produisent la même séquence.
- **CRC16** (`calculer_crc16`) : implémentation polynomiale `0xA001` pour la détection d'erreurs sur les
  trames radio reçues.
- **Anti-rejeu** : dans `reception_trame_radio`, on conserve le dernier `nonce` reçu et on rejette tout
  paquet ayant le même nonce que le précédent (affichage d'un `R` sur la matrice LED).
- **Feedback visuel** : la matrice 5×5 affiche un pixel central à chaque trame correctement reçue, un `C`
  en cas d'échec CRC, un `R` en cas de rejeu, et la première lettre de la dernière commande de configuration.
- **Cycle de vie** : `uBit.init()` puis activation de la radio (`uBit.radio.enable()`, `setGroup(77)`),
  enregistrement du handler radio, et boucle infinie de lecture UART.

---

## 4. Protocoles de communication

### 4.1 Trame radio reçue (capteur → passerelle) — 21 octets

| Offset      | Taille | Champ              | Description                                                    |
| ----------- | ------ | ------------------ | -------------------------------------------------------------- |
| `[0]`       | 1      | Identifiant réseau | Toujours `0xA1`.                                               |
| `[1..2]`    | 2      | Nonce              | `uint16_t` little-endian, utilisé pour l'anti-rejeu et le PRNG.|
| `[3..18]`   | 16     | Payload chiffré    | XOR-é avec `CLE_RADIO` + nonce. Contient les mesures capteur.  |
| `[19..20]`  | 2      | CRC16              | Calculé sur les 19 octets précédents.                          |

**Payload déchiffré (16 octets)** :

| Offset    | Taille | Champ        | Format / Unité                                      |
| --------- | ------ | ------------ | --------------------------------------------------- |
| `[0]`     | 1      | `num_capteur`| Identifiant unique de l'objet (`uint8_t`).          |
| `[1..4]`  | 4      | `temp`       | Température en 0.01 °C (`int32_t`).                 |
| `[5..6]`  | 2      | `hum`        | Humidité relative en 0.01 %rH (`uint16_t`).         |
| `[7..10]` | 4      | `press`      | Pression en hPa (`uint32_t`).                       |
| `[11..14]`| 4      | `lum`        | Luminosité en lux (`uint32_t`).                     |
| `[15]`    | 1      | padding      | Réservé, doit valoir `0x00`.                        |

### 4.2 Trame UART envoyée (passerelle → serveur)

| Offset             | Taille | Champ              | Description                                        |
| ------------------ | ------ | ------------------ | -------------------------------------------------- |
| `[0]`              | 1      | Identifiant        | Toujours `0xC3`.                                   |
| `[1..2]`           | 2      | Nonce UART         | `uint16_t`, incrémenté à chaque émission.          |
| `[3]`              | 1      | Taille du payload  | Longueur N de la chaîne JSON chiffrée.             |
| `[4..N+3]`         | N      | Payload chiffré    | JSON XOR-é avec `CLE_UART` + nonce UART.           |
| `[N+4..N+5]`       | 2      | CRC16              | Calculé sur les `4 + N` octets précédents.         |

**Format JSON (avant chiffrement)** :

```json
{"id":1,"t":2502,"h":4267,"p":995,"l":50}
```

### 4.3 Trame radio envoyée (passerelle → capteur, config affichage)

| Offset     | Taille | Champ            | Description                                                   |
| ---------- | ------ | ---------------- | ------------------------------------------------------------- |
| `[0]`      | 1      | Identifiant      | Toujours `0xB2`.                                              |
| `[1..2]`   | 2      | `nonce_cfg`      | Nonce 16 bits tiré aléatoirement à chaque envoi.              |
| `[3..N+2]` | N      | Payload chiffré  | Lettres majuscules de configuration (ex : `TLH`) XOR-ées.     |

### 4.4 Commande de configuration reçue sur UART

La passerelle attend une **chaîne ASCII courte** (≤ 5 caractères) terminée par `\r\n`, par exemple :

- `T\r\n`, `TL\r\n`, `TLH\r\n`, `HLTP\r\n`, ...

Les 4 premiers caractères sont chiffrés et diffusés en radio vers l'objet capteur (cf. § 4.3). La première
lettre est également affichée brièvement sur la matrice LED de la passerelle (feedback visuel).

---

## 5. Sécurité

Le sujet insiste sur la nécessité d'un **protocole sécurisé** car l'entreprise prévoit de déployer plusieurs
objets. Notre passerelle met en œuvre trois mécanismes complémentaires :

1. **Confidentialité** — Chaque payload (radio ou UART) est XOR-é avec un flux pseudo-aléatoire généré par
   XORSHIFT32 ; l'écoute passive ne donne donc accès qu'à un flux chiffré.
2. **Intégrité** — Un CRC16 protège les trames radio contre les altérations (bruit, brouillage, etc.).
3. **Anti-rejeu** — Le nonce 2 octets est vérifié à chaque réception : un attaquant qui rejoue une trame
   déjà reçue verra son paquet rejeté.

> Les clés `CLE_RADIO` (`"IoT2026!"`) et `CLE_UART` (`"UART2026"`) sont volontairement codées en dur dans le
> firmware ; dans un contexte réel, elles seraient provisionnées au flashage et stockées hors du dépôt.

---

## 6. Prérequis

- Une carte **BBC micro:bit V2** (l'environnement CODAL utilisé suppose la V2).
- L'environnement de build **Yotta** ou le projet template
  [`microbit-v2-samples`](https://github.com/lancaster-university/microbit-v2-samples) de Lancaster University.
- Un câble **USB** pour le flashage et la communication série avec le PC.
- Côté hôte : un terminal série (`screen`, `minicom`, `picocom`, etc.) ou le serveur Python du dossier
  `serveur/` pour piloter la passerelle.

---

## 7. Compilation et flashage

Le projet est conçu pour s'intégrer dans le squelette `microbit-v2-samples` (CODAL).
La procédure typique consiste à :

1. Cloner le template :
   ```bash
   git clone https://github.com/lancaster-university/microbit-v2-samples.git
   cd microbit-v2-samples
   ```
2. Copier le contenu de ce dossier `microbit-gateway/` à la racine du template (le `main.cpp` remplace celui
   fourni par défaut, le sous-dossier `drivers/` est conservé tel quel).
3. Compiler le firmware :
   ```bash
   python build.py
   ```
4. Récupérer le binaire `MICROBIT.hex` généré dans `MICROBIT/` et le glisser-déposer sur le lecteur USB
   `MICROBIT` exposé par la carte.

---

## 8. Utilisation

1. Flasher la passerelle (cf. § 7).
2. Connecter la carte au PC en USB ; le port série apparaît typiquement sous `/dev/ttyACM0` (Linux),
   `/dev/tty.usbmodemXXXX` (macOS) ou `COMx` (Windows).
3. Au démarrage, la carte fait défiler `"GW SEC"` sur sa matrice LED — c'est le signal que le firmware est prêt.
4. Lancer le serveur Python du dossier `serveur/` en lui indiquant le port série de la passerelle. Le serveur :
   - reçoit les trames UART chiffrées et les déchiffre,
   - alimente la base / le fichier de stockage,
   - relaie les commandes de configuration envoyées par l'application Android.
5. Les évènements visibles sur la matrice LED :
   - Pixel central qui clignote → trame radio reçue et validée.
   - `C` → trame radio rejetée pour CRC invalide.
   - `R` → trame radio rejetée pour cause de rejeu (nonce déjà vu).
   - Une lettre (`T`, `L`, `H`, ...) → première lettre de la dernière commande de configuration reçue.

---

## 9. Configuration

Les principaux paramètres se trouvent en tête de `main.cpp` :

```cpp
#define RADIO_GROUP 77
static const uint8_t CLE_RADIO[8] = { ... };   // "IoT2026!"
static const uint8_t CLE_UART[8]  = { ... };   // "UART2026"
```

- **`RADIO_GROUP`** doit être identique sur la passerelle et sur tous les objets capteurs.
- Les clés radio / UART doivent être identiques côté capteur et côté serveur Python respectivement.

