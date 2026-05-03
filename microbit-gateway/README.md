# Micro:bit Passerelle (GW)

Firmware du micro:bit branché au PC. Son rôle est de faire le pont entre les capteurs (radio) et le serveur Python (UART).

---

## Ce que fait ce code

- Reçoit les trames radio chiffrées du micro:bit capteur
- Vérifie l'intégrité (CRC16) et l'anti-rejeu (nonce 2 octets)
- Déchiffre le payload avec XORSHIFT32 + `CLE_RADIO`
- Rechiffre les données en JSON avec XORSHIFT32 + `CLE_UART` et les envoie au serveur Python via UART binaire
- Reçoit les commandes de config depuis Python (ex: `TLH`) et les relaie au capteur par radio, chiffrées

> Pour la démonstration, la trame radio chiffrée est aussi envoyée en hex sur l'UART avant d'être déchiffrée, ce qui permet de visualiser les deux niveaux de chiffrement dans les logs Python.

---

## Sécurité

| Couche | Algorithme | Clé |
|--------|-----------|-----|
| Radio → GW | XORSHIFT32 + nonce | `IoT2026!` |
| GW → Python | XORSHIFT32 + nonce | `UART2026` |

Le nonce est initialisé aléatoirement au démarrage et incrémenté à chaque trame — deux trames identiques produiront toujours un chiffré différent.

---

## Compilation et flash

Ce firmware utilise le SDK **yotta** (microbit-dal).

```bash
# Depuis le dossier microbit-samples/
yt build

# Copier le .hex sur le micro:bit (Linux)
cp build/bbc-microbit-classic-gcc/source/microbit-samples-combined.hex /mnt/Microbit

# Windows : glisser-déposer le .hex sur le lecteur MICROBIT
```

Le micro:bit affiche `GW SEC` au démarrage pour confirmer que le firmware est chargé.

---

## Format des trames

**Radio reçue — 21 octets**
```
[0]      0xA1         marqueur
[1..2]   nonce        uint16_t
[3..18]  payload      16 octets chiffrés (num_capteur, t, h, p, l)
[19..20] CRC16
```

**UART envoyée**
```
[0]      0xC3         marqueur
[1..2]   nonce UART   uint16_t
[3]      taille JSON
[4..N]   JSON chiffré  {"id":1,"t":2502,"h":4267,"p":995,"l":50}
[N+1..2] CRC16
```