# Application Android — Mini Architecture IoT

Application Android développée dans le cadre du mini-projet **Développement embarqué et IoT** (CPE Lyon, 3IRC).
Elle constitue la brique « client mobile » de l'architecture *objet — passerelle — serveur* et permet à un utilisateur
de configurer l'ordre d'affichage des données d'un capteur (micro:bit) et de visualiser les valeurs renvoyées par
le serveur.

---

## 1. Contexte du projet

L'architecture globale du projet est la suivante :

```
[micro:bit capteur]  --RF 2.4GHz-->  [micro:bit passerelle (USB)]  <--UART-->  [Serveur (PC)]  <--UDP/WiFi-->  [Application Android]
```

- Le capteur (micro:bit) collecte des données (température, luminosité, humidité, ...) et les envoie à la passerelle.
- La passerelle relaie les données vers le serveur via le port série (UART).
- Le serveur stocke les données et expose une interface UDP sur le port **10000** (par défaut).
- **L'application Android** (ce dossier) communique avec le serveur en UDP pour :
  - demander les dernières valeurs collectées,
  - définir l'ordre d'affichage des données sur l'écran OLED du capteur,
  - recevoir et afficher les valeurs renvoyées par le serveur.

---

## 2. Fonctionnalités

L'application répond aux besoins listés dans le sujet :

| Fonctionnalité                          | Description                                                                                              |
| --------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| Choix du serveur de destination         | Saisie libre de l'adresse IP et du port du serveur (par défaut `10000`).                                 |
| Envoi de l'ordre d'affichage            | Envoi d'une chaîne de lettres majuscules (`TLH`, `LTH`, `HLT`, ...) indiquant l'ordre d'affichage OLED.  |
| Demande de rafraîchissement des valeurs | Bouton « Actualiser » qui envoie la requête `getValues()` au serveur (cf. protocole du sujet).           |
| Réception des données                   | Écoute UDP non bloquante dans un thread dédié, affichage en temps réel des données reçues.               |
| Communication uniquement en UDP         | Aucun ACK n'est attendu, conformément au sujet.                                                          |

---

## 3. Interface utilisateur

L'écran principal (`activity_main.xml`) est composé de :

1. **Adresse IP du serveur** + **Port** (champs éditables, valeurs par défaut `192.168.1.1` / `10000`).
2. **Bouton « Démarrer / Arrêter la Réception »** : démarre ou arrête l'écoute UDP sur le port indiqué.
3. **Zone d'affichage des données reçues** : affiche le dernier message reçu depuis le serveur.
4. **Champ « Ordre d'affichage »** + **Bouton « Envoyer Configuration »** : envoie la configuration au serveur.
5. **Bouton « Actualiser les Valeurs »** : envoie la requête `getValues()` au serveur.

Toutes les chaînes de l'interface sont externalisées dans `app/src/main/res/values/strings.xml` (FR).

---

## 4. Architecture du code

L'application est volontairement minimaliste : **une seule activité** suffit à couvrir les besoins du sujet.

```
android/
├── app/
│   ├── build.gradle.kts                          # Configuration du module applicatif
│   └── src/main/
│       ├── AndroidManifest.xml                   # Permissions INTERNET / ACCESS_NETWORK_STATE
│       ├── java/fr/cpe/miniarchi/
│       │   └── MainActivity.java                 # Activité principale (UI + logique UDP)
│       └── res/
│           ├── layout/activity_main.xml          # Interface graphique
│           ├── values/strings.xml                # Chaînes en français
│           └── ...                               # Thèmes, icônes, etc.
├── build.gradle.kts                              # Configuration racine du projet
├── gradle/libs.versions.toml                     # Catalogue de versions des dépendances
├── settings.gradle.kts                           # Déclaration des modules Gradle
└── gradlew / gradlew.bat                         # Wrapper Gradle
```

### Points techniques notables (`MainActivity.java`)

- **Émission UDP** (`sendUDP`) :
  - Exécutée dans un `ExecutorService` (le réseau est interdit sur le thread UI Android).
  - Force l'utilisation d'une adresse **IPv4** (`Inet4Address`) — utile en simulateur où une adresse IPv6 peut être résolue par défaut.
- **Réception UDP** (`startListening` / `stopListening`) :
  - Socket lié à `0.0.0.0` pour accepter tous les paquets entrants sur le port choisi.
  - Boucle de réception dans un thread séparé, fermeture propre du socket en cas d'arrêt.
  - Mise à jour de l'UI via un `Handler` lié au `Looper` principal.
- **Cycle de vie** : libération des ressources réseau et du pool de threads dans `onDestroy()`.

---

## 5. Protocole de communication

L'application reste fidèle au protocole décrit dans le sujet et dans l'exemple `controller.py` :

| Direction               | Message envoyé / reçu       | Sens                                                                  |
| ----------------------- | --------------------------- | --------------------------------------------------------------------- |
| Android → Serveur       | `getValues()`               | Demande au serveur les dernières valeurs collectées.                  |
| Android → Serveur       | `TLH`, `LTH`, `HLT`, ...    | Définit l'ordre d'affichage des données sur l'écran OLED de l'objet.  |
| Serveur → Android       | Données brutes (ou JSON)    | Valeurs envoyées spontanément par le serveur, affichées dans l'app.   |

Les lettres correspondent (de manière minimale) à :

- `T` — Température
- `L` — Luminosité
- `H` — Humidité

D'autres capteurs peuvent être ajoutés en suivant la même logique (lettre majuscule = type de donnée).

---

## 6. Prérequis

- **Android Studio** (version récente, *Narwhal* ou supérieure).
- **JDK 11** (configuré dans `app/build.gradle.kts`).
- **Android SDK 36** pour la compilation, **API 24+ (Android 7.0)** pour l'exécution.
- Un **téléphone Android** ou un **émulateur** sur le même réseau que le serveur.

> Lors de l'utilisation d'un téléphone physique, il faut être connecté au **même réseau Wi-Fi** que le PC qui exécute
> le serveur. Sur émulateur, l'adresse `10.0.2.2` permet d'atteindre le `localhost` du PC hôte.

---

## 7. Compilation et exécution

Depuis le dossier `android/` :

```bash
# Build debug
./gradlew assembleDebug

# Installation sur un appareil connecté
./gradlew installDebug
```

Sinon, ouvrir simplement le dossier `android/` dans **Android Studio** et lancer le module `app` sur un appareil ou
un émulateur.

---

## 8. Utilisation

1. Démarrer le serveur sur le PC (cf. dossier `serveur/`).
2. Lancer l'application sur le téléphone / l'émulateur.
3. Renseigner :
   - l'**adresse IP** du serveur (ex : `192.168.1.42` en réseau réel, `10.0.2.2` en émulateur),
   - le **port** d'écoute du serveur (par défaut `10000`).
4. Appuyer sur **« Démarrer la Réception »** : l'application écoute désormais les paquets UDP entrants.
5. Pour configurer l'ordre d'affichage, saisir une chaîne (ex : `TLH`) puis appuyer sur **« Envoyer Configuration »**.
6. Le bouton **« Actualiser les Valeurs »** envoie `getValues()` au serveur ; la réponse s'affiche dans la zone
   « Données reçues ».

---

## 9. Permissions

Déclarées dans `AndroidManifest.xml` :

- `android.permission.INTERNET` — nécessaire pour l'émission et la réception UDP.
- `android.permission.ACCESS_NETWORK_STATE` — utile pour vérifier l'état de connectivité du téléphone.

Aucune permission « runtime » n'est demandée à l'utilisateur (toutes les permissions sont de niveau « normal »).
