# Passerelle / Serveur IoT

Serveur Python faisant le rôle de passerelle entre le micro:bit (via USB/UART) et l'application Android (via UDP).

---

## Prérequis

- Python 3.10 ou supérieur
- La librairie `pyserial`

```bash
pip install pyserial
```

---

## Lancer le serveur

```bash
cd Server
python controller.py
```

Le serveur démarre sur le **port UDP 10000** et écoute sur toutes les interfaces réseau.

Si le micro:bit n'est pas branché, le serveur démarre en **mode simulation** (le protocole UDP fonctionne quand même).

---

## Configuration

Dans `controller.py`, modifiez ces variables si nécessaire :

| Variable | Valeur par défaut | Description |
|---|---|---|
| `UDP_PORT` | `10000` | Port UDP d'écoute |
| `SERIAL_PORT` | `COM3` | Port série du micro:bit (Windows: `COM3`, Linux: `/dev/ttyACM0`) |
| `SERIAL_BAUD` | `115200` | Vitesse UART (doit correspondre au code micro:bit) |
| `DATA_FILE` | `donnees_capteurs.txt` | Fichier de stockage des mesures |

> **Trouver le bon port série sur Windows** : Gestionnaire de périphériques → Ports (COM et LPT) → brancher le micro:bit et voir quel port apparaît.

---

## Format des données capteurs (micro:bit → Serveur)

Le micro:bit envoie ses données via UART. Deux formats sont acceptés :

**Format clé:valeur (recommandé)**
```
T:24.5,L:312,H:58,P:1012
```

**Format JSON**
```json
{"T": 24.5, "L": 312, "H": 58, "P": 1012}
```

| Lettre | Capteur | Unité |
|---|---|---|
| `T` | Température | °C |
| `L` | Luminosité | lux |
| `H` | Humidité | % |
| `P` | Pression | hPa |

---

## Protocole UDP (Android → Serveur)

L'application Android communique avec le serveur via UDP sur le port **10000**.

| Commande | Description | Réponse |
|---|---|---|
| `getValues()` | Dernière mesure reçue | JSON de la mesure |
| `getHistory()` | 10 dernières mesures | Liste JSON |
| `register` | S'inscrire au push temps réel | `{"status": "ok"}` |
| `unregister` | Se désinscrire du push | `{"status": "ok"}` |
| `TLH` / `HTP` / `TLHP` ... | Ordre d'affichage OLED | `{"status": "ok", "config": "TLH"}` |

### Configurations d'affichage

Les lettres indiquent l'ordre d'affichage sur l'écran OLED du micro:bit :
- `TLH` → Température, puis Luminosité, puis Humidité
- `HTP` → Humidité, puis Température, puis Pression
- Les lettres doivent appartenir à `{T, L, H, P}` sans répétition

---

## Exemple de réponses JSON

**getValues()** après réception de données :
```json
{
  "timestamp": "2026-04-24T10:30:00.123456",
  "raw": "T:24.5,L:312,H:58,P:1012",
  "T": 24.5,
  "L": 312,
  "H": 58,
  "P": 1012
}
```

**getValues()** si aucune donnée reçue :
```json
{"message": "Aucune donnée disponible"}
```

---

## Tester sans micro:bit

Un script de test est fourni pour vérifier que le serveur répond correctement :

```bash
# Terminal 1 — lancer le serveur
python controller.py

# Terminal 2 — lancer les tests
python test_server.py
```

---

## Stockage des données

Chaque mesure reçue est automatiquement sauvegardée dans `donnees_capteurs.txt` (une entrée JSON par ligne) :

```
{"timestamp": "2026-04-24T10:30:00", "raw": "T:24.5,L:312,H:58,P:1012", "T": 24.5, "L": 312, "H": 58, "P": 1012}
{"timestamp": "2026-04-24T10:30:05", "raw": "T:24.6,L:310,H:57,P:1013", "T": 24.6, "L": 310, "H": 57, "P": 1013}
```

---

## Architecture

```
micro:bit (capteurs)
      │  UART / USB
      ▼
controller.py  ──────────────────────────────►  donnees_capteurs.txt
      │  UDP port 10000
      ▼
Application Android
```

- **Thread principal** : serveur UDP
- **Thread SerialReader** : lecture continue du port série
