# Serveur Python — Mini Architecture IoT

Serveur central développé dans le cadre du mini-projet **Développement embarqué et IoT** (CPE Lyon, 3IRC).

Ce serveur, exécuté sur un PC connecté en USB à la passerelle micro:bit, fait le **pont entre la
passerelle (UART)** et **l'application Android (UDP)**. Il déchiffre les trames capteur reçues, les
stocke dans une base SQLite et expose une interface UDP permettant à l'application Android de
consulter les dernières valeurs et d'envoyer des ordres de configuration d'affichage.

---

## 1. Contexte du projet

L'architecture globale du projet est la suivante :

```
[micro:bit capteur]  --RF 2.4GHz-->  [micro:bit passerelle (USB)]  <--UART-->  [Serveur (PC)]  <--UDP/WiFi-->  [Application Android]
                                                                                ^^^^^^^^^^^^^^
                                                                                (ce dossier)
```

- Le serveur reçoit les trames UART **binaires chiffrées** envoyées par la passerelle micro:bit.
- Il les **déchiffre** (XORSHIFT32 + CRC16), parse le JSON et le persiste dans une base **SQLite** ainsi
  que dans un fichier texte de sauvegarde (`values.txt`).
- Il expose un **serveur UDP multithread** qui répond aux requêtes de l'application Android :
  - `getValues()` → renvoie la dernière trame JSON reçue,
  - `TLH`, `LTHP`, ... → relaie la configuration d'affichage à la passerelle via UART.
- Il journalise l'ensemble des échanges (UART RX/TX et UDP RX/TX) dans une table dédiée.

---

## 2. Fonctionnalités

Le serveur répond aux besoins listés dans le sujet pour la partie « serveur » :

| Fonctionnalité                              | Description                                                                                                  |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Réception UART chiffrée                     | Synchronisation sur le marqueur `0xC3`, lecture du nonce, du payload et du CRC16, puis déchiffrement XORSHIFT32. |
| Stockage des données capteur                | Insertion dans la base SQLite `iot_project.db` + sauvegarde brute (mode *append*) dans `values.txt`.         |
| Serveur UDP multithread                     | Écoute sur `0.0.0.0:LISTEN_PORT`, traitement concurrent grâce à `socketserver.ThreadingMixIn`.               |
| Requête `getValues()`                       | Renvoie la dernière trame JSON reçue (ou un message d'attente si la mémoire est vide).                       |
| Relai des commandes de configuration        | Validation des lettres (`TLHP`), envoi sur UART à la passerelle, accusé `{"status":"success","config":...}`. |
| Journal de trafic (audit)                   | Toutes les communications (UART RX/TX, UDP RX/TX) sont horodatées et enregistrées en BDD.                    |
| Gestion multi-objets                        | La table `Module_IoT` enregistre chaque capteur (par `num_capteur` extrait du JSON) ; auto-enregistrement.   |
| Auto-détection du port série                | Détection automatique des ports `mbed` / `microbit` / `usb serial device` ; repli sur `COM_PORT`.            |

---

## 3. Architecture du code

Le serveur est compact : **un seul script Python `controller.py`** héberge l'ensemble de la logique. Le
schéma SQL est isolé dans `schema_base.sql` et instancié via `setup_db.py`.

```
serveur/
├── controller.py          # Programme principal (UART + UDP + SQLite + crypto)
├── setup_db.py            # Script d'initialisation de la base SQLite
├── schema_base.sql        # DDL : tables Module_IoT, Historique_Donnees, Journal_Trafic
├── iot_project.db         # Base SQLite (générée par setup_db.py, présente après init)
└── values.txt             # Sauvegarde texte brute des JSON reçus (append)
```

### Points techniques notables (`controller.py`)

- **Cryptographie symétrique avec la passerelle** : implémentation Python identique du PRNG XORSHIFT32
  (`xorshift32`, `initialiser_prng`) et du **CRC16** (`calculer_crc16`) ; la clé `CLE_UART` (`"UART2026"`)
  est partagée avec le firmware de `microbit-gateway/`.
- **Lecture de trame robuste** (`lire_trame_uart`) : synchronisation sur le marqueur `0xC3`, capture
  tolérée des lignes texte de debug (préfixées `[GW RAW]`) émises par la passerelle entre deux trames.
- **Persistance** : insertion en SQLite + dump texte (`values.txt`), sous protection d'un
  `threading.Lock` pour le partage de la « dernière trame » entre le thread UART et le thread UDP.
- **Serveur UDP** : `socketserver.ThreadingMixIn + UDPServer` ; chaque requête est traitée par un
  `ClientRequestHandler` dédié. L'objet `udp_server.serial_conn` permet au handler UDP d'écrire sur
  l'UART pour relayer les ordres de configuration.
- **Validation des configurations** (`check_format_validity`) : seules les chaînes composées
  exclusivement de lettres `{T, L, H, P}` **distinctes** sont acceptées (rejet de `TT`, `XLT`, ...).

---

## 4. Protocoles de communication

### 4.1 Trame UART reçue (passerelle → serveur)

| Offset             | Taille | Champ              | Description                                        |
| ------------------ | ------ | ------------------ | -------------------------------------------------- |
| `[0]`              | 1      | Identifiant        | Toujours `0xC3`.                                   |
| `[1..2]`           | 2      | Nonce UART         | `uint16_t` little-endian, utilisé pour le PRNG.    |
| `[3]`              | 1      | Taille du payload  | Longueur N de la chaîne JSON chiffrée.             |
| `[4..N+3]`         | N      | Payload chiffré    | JSON XOR-é avec `CLE_UART` + nonce UART.           |
| `[N+4..N+5]`       | 2      | CRC16              | Calculé sur les `4 + N` octets précédents.         |

**Format JSON (après déchiffrement)** :

```json
{"id":1,"t":2502,"h":4267,"p":995,"l":50}
```

Conventions d'unités telles que reçues :

- `t` : température en **0.01 °C** (`2502` → 25.02 °C),
- `h` : humidité en **0.01 %rH** (`4267` → 42.67 %),
- `p` : pression en **hPa** (`995` → 995 hPa),
- `l` : luminosité en **lux**.

### 4.2 Interface UDP (Android ↔ serveur)

| Sens                  | Message                                  | Description                                                              |
| --------------------- | ---------------------------------------- | ------------------------------------------------------------------------ |
| Android → Serveur     | `getValues()`                            | Demande la dernière trame JSON reçue de la passerelle.                   |
| Serveur → Android     | JSON brut (ex : `{"id":1,"t":2502,...}`) | Réponse à `getValues()` ; ou message texte « Pas de donnees en memoire ».|
| Android → Serveur     | `TLH`, `LTHP`, ...                       | Configuration d'affichage à propager au capteur (via UART).              |
| Serveur → Android     | `{"status":"success","config":"TLH"}`    | Accusé de réception après relai sur UART.                                |

### 4.3 Trame UART émise (serveur → passerelle)

La commande validée est encapsulée en ASCII et terminée par `\r\n`, par exemple :

```
TLH\r\n
```

La passerelle se charge ensuite de chiffrer puis de diffuser cette commande en radio vers l'objet
capteur (cf. `microbit-gateway/README.md`, § 4.3).

---

## 5. Base de données

Le schéma `schema_base.sql` définit trois tables :

| Table                | Rôle                                                                                                   |
| -------------------- | ------------------------------------------------------------------------------------------------------ |
| `Module_IoT`         | Inventaire des objets connectés (`num_capteur`, `id_reseau`, `emplacement`, format d'affichage actif). |
| `Historique_Donnees` | Historique horodaté des relevés (`val_temp`, `val_lum`, `val_hum`, `val_pres`), lié à `Module_IoT`.    |
| `Journal_Trafic`     | Journal d'audit de toutes les communications UART / UDP (canal, sens, source, payload brut, date).    |

À la première réception d'un nouveau `num_capteur`, le serveur crée automatiquement l'entrée
correspondante dans `Module_IoT` (`id_reseau = "capteur_<n>"`), ce qui permet la **gestion native de
plusieurs objets** sans intervention manuelle.

---

## 6. Sécurité

Le serveur partage avec la passerelle les mêmes primitives :

1. **Confidentialité UART** — chaque payload est chiffré par XOR contre un flux pseudo-aléatoire
   généré par XORSHIFT32 ; la clé `CLE_UART` (`"UART2026"`) doit être identique côté firmware passerelle.
2. **Intégrité** — un CRC16 protège la trame UART contre toute altération ; en cas d'écart, le serveur
   journalise une erreur et ignore la trame.
3. **Validation stricte des commandes UDP** — seules les configurations composées de lettres
   `{T, L, H, P}` **distinctes** sont relayées sur l'UART, ce qui rend impossible l'injection de
   commandes série arbitraires depuis le réseau.

> Le serveur conserve par ailleurs un **journal complet** des échanges dans `Journal_Trafic`, utile pour
> l'audit lors de la démonstration.

---

## 7. Prérequis

- **Python ≥ 3.9** (testé sur 3.11 / 3.12).
- Module Python **`pyserial`** :
  ```bash
  pip install pyserial
  ```
- Une **passerelle micro:bit** flashée avec le firmware de `microbit-gateway/`, connectée en USB.
- Le module **`sqlite3`** (inclus dans la bibliothèque standard Python).

---

## 8. Installation et exécution

Depuis le dossier `serveur/` :

1. (Optionnel) Créer un environnement virtuel et installer la dépendance :
   ```bash
   python -m venv .venv
   source .venv/bin/activate         # Linux / macOS
   .venv\Scripts\activate            # Windows
   pip install pyserial
   ```
2. **Initialiser la base SQLite** (une seule fois, ou pour repartir d'un état propre) :
   ```bash
   python setup_db.py
   ```
3. **Lancer le serveur** :
   ```bash
   python controller.py
   ```

Au démarrage, le serveur :

- ouvre le port série de la passerelle (auto-détection ; sinon repli sur `COM_PORT`),
- ouvre le socket UDP sur `0.0.0.0:LISTEN_PORT`,
- affiche `*** Serveur UDP en écoute sur le port ... ***` et reste en attente.

Pour l'arrêter proprement : **Ctrl + C** (la fermeture des sockets / du port série est garantie par
le bloc `finally`).

---

## 9. Configuration

Les principaux paramètres se trouvent en tête de `controller.py` :

```python
BIND_IP     = "0.0.0.0"
LISTEN_PORT = 10005
COM_PORT    = "COM4"          # port série utilisé si l'auto-détection échoue
BAUD_RATE   = 115200
DB_FILE     = "iot_project.db"
BACKUP_TXT  = "values.txt"

CLE_UART    = bytes([0x55, 0x41, 0x52, 0x54, 0x32, 0x30, 0x32, 0x36])  # "UART2026"
```

Quelques points d'attention :

- **Port UDP** : `10005` côté serveur, alors que le sujet suggère `10000`. Côté application Android,
  il faut donc **saisir `10005`** dans le champ Port (ou ajuster `LISTEN_PORT` à `10000` ici).
- **Port série** : sous Linux/macOS, modifier `COM_PORT` en `/dev/ttyACM0`, `/dev/tty.usbmodemXXXX`, ...
  L'auto-détection couvre la plupart des cas (mots-clés `mbed`, `microbit`, `usb serial device`).
- **Clé UART** : doit être strictement identique à la constante `CLE_UART` du firmware passerelle.

---

## 10. Utilisation typique (démo)

Une session type, telle qu'elle sera présentée lors de la démonstration :

1. Flasher la passerelle et l'objet capteur (cf. `microbit-gateway/` et `microbit-node-1/`).
2. Connecter la passerelle au PC en USB ; vérifier que le port apparaît côté OS.
3. `python setup_db.py` (au moins lors de la première utilisation).
4. `python controller.py` → le terminal affiche les trames reçues :
   ```
   [UART CHIFFRÉ]   nonce=12345 | 7B 22 69 ...
   [UART DÉCHIFFRÉ] {"id":1,"t":2502,"h":4267,"p":995,"l":50}
   [BDD] Capteur 1 (...) -> Temp:25.02°C Hum:42.67% Pres:9.95hPa Lum:50lux
   ```
5. Sur le téléphone, ouvrir l'application Android et renseigner l'IP du PC + le port `10005`.
6. Appuyer sur « **Actualiser les Valeurs** » : le serveur reçoit `getValues()` et renvoie le JSON
   stocké en mémoire.
7. Saisir un ordre d'affichage (par exemple `TLH`) et appuyer sur « **Envoyer Configuration** » :
   le serveur valide la chaîne, la transmet à la passerelle, qui la relaie en radio à l'objet capteur,
   qui réordonne son écran OLED en conséquence.