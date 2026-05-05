# Serveur Python — Mini Architecture IoT

Ce serveur tourne sur le PC connecté en USB à la passerelle micro:bit.
Il reçoit les données capteurs via UART, les stocke en base SQLite
et répond aux requêtes UDP de l'application Android.

---

## Fonctionnalités

- Lecture et déchiffrement des trames UART envoyées par la passerelle
- Stockage des mesures dans une base SQLite (`iot_project.db`) et dans `values.txt`
- Serveur UDP multithread qui répond à `getValues()` et relaie les configs d'affichage (`TLH`, `TLHP`…) à la passerelle
- Enregistrement automatique des nouveaux capteurs dans la base
- Journal de tous les échanges UART/UDP dans la table `Journal_Trafic`

---

## Base de données

Trois tables dans `iot_project.db` :

| Table | Contenu |
|-------|---------|
| `Module_IoT` | Capteurs enregistrés (num, réseau, emplacement, format d'affichage) |
| `Historique_Donnees` | Relevés horodatés (température, humidité, pression, luminosité) |
| `Journal_Trafic` | Historique de tous les échanges UART/UDP |

---

## Lancement

```bash
# 1. Installer la dépendance
pip install pyserial

# 2. Initialiser la base (une seule fois)
python setup_db.py

# 3. Lancer le serveur
python controller.py
```

Arrêt : **Ctrl + C**

---

## Configuration

Dans `controller.py` :

```python
LISTEN_PORT = 10005   # port UDP (à renseigner dans l'app Android)
COM_PORT    = "COM4"  # port série (Linux : /dev/ttyACM0)
BAUD_RATE   = 115200
```