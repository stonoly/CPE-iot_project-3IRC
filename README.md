# Mini Architecture IoT — CPE Lyon, 3IRC

Mini-projet du module **Développement embarqué et IoT** (CPE Lyon, promotion 2026).

L'objectif est de mettre en place une architecture IOT complète : un objet capteur micro:bit
mesure la température / humidité / pression / luminosité d'un bureau, transmet ses relevés en radio à
une passerelle, qui les remonte à un serveur Python via USB. Une application Android permet alors de
consulter ces relevés et de reconfigurer à distance l'ordre d'affichage des données sur l'écran OLED
de l'objet.

---

## 1. Architecture

```
┌─────────────────────┐   RF 2.4 GHz   ┌──────────────────────────┐   UART (USB)   ┌─────────────────┐   UDP / WiFi   ┌──────────────────┐
│  Objet capteur      │───────────────►│  Passerelle micro:bit     │──────────────►│  Serveur Python │───────────────►│  App. Android    │
│  (micro:bit + BME280│◄───────────────│  (micro:bit + USB)        │◄──────────────│  (PC, SQLite)   │◄───────────────│  (smartphone)    │
│   + TSL256x + OLED) │  config TLHP   │                           │   config TLHP │                 │   getValues()  │                  │
└─────────────────────┘                └──────────────────────────┘                └─────────────────┘                └──────────────────┘
       microbit-node-1/                       microbit-gateway/                            serveur/                          android/
```

Chaque maillon de la chaîne fait l'objet d'un dossier dédié à la racine de ce dépôt, accompagné de son
propre README détaillé :

| Dossier                                             | Rôle                                                                        | Langage / Stack       |
| --------------------------------------------------- | --------------------------------------------------------------------------- | --------------------- |
| [`microbit-node-1/`](microbit-node-1/README.md)     | Objet capteur déployé en bureau (mesures + écran OLED).                     | C++ / CODAL micro:bit |
| [`microbit-gateway/`](microbit-gateway/README.md)   | Passerelle radio ↔ USB, gestion de la sécurité applicative.                 | C++ / CODAL micro:bit |
| [`serveur/`](serveur/README.md)                     | Serveur central (UART, UDP, base SQLite, journal de trafic).                | Python 3 / SQLite     |
| [`android/`](android/README.md)                     | Application mobile de configuration et de visualisation des données.        | Java / Android SDK    |

---

## 2. Fonctionnalités globales

Voici les fonctionnalités que nous avons implémentées :

- **Mesures multi-capteurs** (température, humidité, pression, luminosité) sur l'objet déployé.
- **Communication radio 2.4 GHz** sécurisée entre l'objet et la passerelle.
- **Communication UART** chiffrée entre la passerelle et le serveur.
- **Stockage côté serveur** dans une base SQLite + sauvegarde texte (`values.txt`).
- **Interface UDP** pour l'application Android (`getValues()` + commandes de configuration).
- **Affichage configurable** sur l'écran OLED de l'objet (lettres `T`, `L`, `H`, `P` dans l'ordre voulu).
- **Communication bidirectionnelle** Android ↔ serveur ↔ passerelle ↔ objet.
- **Gestion multi-objets** : chaque trame inclut un `num_capteur`, et la base s'auto-alimente.
- **Visualisation web** des données via un dashboard Grafana (courbes, jauges, historique).
- **Journal de trafic** : toutes les communications (UART et UDP) sont tracées dans la base de données.

---

## 3. Sécurité applicative

Le sujet demandant un protocole sécurisé pour un déploiement multi-bureaux,
on a implémenté trois mécanismes sur les communications radio et UART.

1. **Confidentialité** — les payloads sont chiffrés par XOR avec un flux
   généré par XORSHIFT32, initialisé à partir d'une clé partagée et du nonce
   de la trame. Deux trames avec le même contenu ne produisent donc jamais
   le même résultat chiffré.
2. **Intégrité** — un CRC16 (polynôme `0xA001`) est calculé sur chaque trame.
   Si les données ont été altérées en transit, le CRC ne correspond plus et
   la trame est rejetée puis journalisée.
3. **Anti-rejeu** — chaque trame embarque un nonce 16 bits. La passerelle
   mémorise le dernier nonce valide de chaque objet et refuse tout paquet
   présentant un nonce déjà utilisé.

Côté serveur, les commandes UDP sont validées strictement : seules les lettres
`T`, `L`, `H`, `P` sans répétition sont acceptées, ce qui empêche d'injecter
du texte arbitraire sur l'UART depuis le réseau.

---

## 4. Prérequis

- Python 3 + `pip install pyserial`
- Docker (pour Grafana)
- Android Studio (pour compiler l'app) ou l'APK directement
- Environnement Yotta (pour compiler les firmwares micro:bit)

## 5. Mise en route rapide

L'ordre recommandé pour faire fonctionner l'architecture complète :

1. **Objet capteur** — flasher la micro:bit du bureau avec le firmware de
   [`microbit-node-1/`](microbit-node-1/README.md).
2. **Passerelle** — flasher la micro:bit raccordée au PC avec le firmware de
   [`microbit-gateway/`](microbit-gateway/README.md).
3. **Serveur** — depuis [`serveur/`](serveur/README.md), initialiser la base puis lancer le contrôleur :
   ```bash
   python setup_db.py
   python controller.py
   ```
4. **Application Android** — depuis [`android/`](android/README.md), installer l'APK sur un téléphone
   connecté au même réseau Wi-Fi que le PC (ou utiliser un émulateur avec `10.0.2.2`), puis renseigner
   l'IP du serveur et le port d'écoute (`10005` par défaut).

Quand tout est lancé, le serveur affiche en console les trames déchiffrées, l'application
Android peut demander les dernières valeurs (`getValues()`) et envoyer un ordre d'affichage (par exemple
`TLH`) qui se propagera jusqu'à l'écran OLED de l'objet.

---

## 6. Conventions et constantes partagées

Les valeurs suivantes doivent être **identiques** dans plusieurs modules pour que la chaîne fonctionne :

| Constante           | Valeur                | Modules concernés                                   |
| ------------------- | --------------------- | --------------------------------------------------- |
| `RADIO_GROUP`       | `77`                  | `microbit-node-1/` et `microbit-gateway/`           |
| `CLE_RADIO`         | `"IoT2026!"` (8 oct.) | `microbit-node-1/` et `microbit-gateway/`           |
| `CLE_UART`          | `"UART2026"` (8 oct.) | `microbit-gateway/` et `serveur/`                   |
| Lettres d'affichage | `T`, `L`, `H`, `P`    | `microbit-node-1/`, `serveur/`, `android/`          |
| Port UDP serveur    | `10005`               | `serveur/` et `android/` (champ Port)               |
| Baud UART           | `115200`              | `microbit-gateway/` (CODAL default) et `serveur/`   |

> Si l'un de ces paramètres est modifié dans un module, il doit **impérativement** l'être dans les
> autres modules concernés.

## 7. EQUIPE
 
- DAVID Manuel
- BIGGERI Emmanuel
- MOLY Pierre
- CHBOUK Hicham