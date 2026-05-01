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

1. **Adresse IP du serveur** + **Port** (champs éditables, valeurs par défaut `10.0.2.2` / `10000`).
   - `10.0.2.2` est l'alias spécial pointant vers le `localhost` du PC hôte **depuis l'émulateur Android**.
   - Pour un téléphone physique, remplacer par l'IP locale du PC (ex : `192.168.1.42`).
2. **Bouton « Démarrer / Arrêter la Réception »** : démarre ou arrête l'écoute UDP sur le port indiqué.
3. **Zone d'affichage des données reçues** : affiche le dernier message reçu depuis le serveur.
4. **Champ « Ordre d'affichage »** + **Bouton « Envoyer Configuration »** : envoie la configuration au serveur.
5. **Bouton « Actualiser les Valeurs »** : envoie la requête `getValues()` au serveur.

> ⚠️ Les boutons d'envoi (Configuration / Actualiser) nécessitent que l'écoute soit démarrée au préalable :
> l'envoi et la réception partagent le **même socket UDP**. Si tu cliques avant d'avoir démarré la réception,
> un toast `Démarrez d'abord la réception` s'affiche.

Toutes les chaînes de l'interface sont externalisées dans `app/src/main/res/values/strings.xml` (FR).

---

## 4. Architecture du code

L'application repose sur une **architecture multi-threads producteur / consommateur**, inspirée des
patrons vus en cours. Le découpage est volontairement simple : **une activité** + **deux threads
dédiés au réseau** + **deux mécanismes de communication inter-threads**.

```
android/
├── app/
│   ├── build.gradle.kts                          # Configuration du module applicatif
│   └── src/main/
│       ├── AndroidManifest.xml                   # Permissions INTERNET / ACCESS_NETWORK_STATE
│       ├── java/fr/cpe/miniarchi/
│       │   ├── MainActivity.java                 # Activité principale (UI + orchestration)
│       │   ├── NetworkThread.java                # Thread d'envoi UDP (consomme une BlockingQueue)
│       │   └── NetworkReceiveThread.java         # Thread de réception UDP (notifie via un Listener)
│       └── res/
│           ├── layout/activity_main.xml          # Interface graphique
│           ├── values/strings.xml                # Chaînes en français
│           └── ...                               # Thèmes, icônes, etc.
├── build.gradle.kts                              # Configuration racine du projet
├── gradle/libs.versions.toml                     # Catalogue de versions des dépendances
├── settings.gradle.kts                           # Déclaration des modules Gradle
└── gradlew / gradlew.bat                         # Wrapper Gradle
```

### Vue d'ensemble du flot de données

```
                ┌─────────────────────────────────────────────┐
                │              MainActivity (UI)              │
                └─────────────────────────────────────────────┘
                       │ add("ip:port:msg")          ▲
                       ▼                             │ listener.onEventInMyThread()
                ┌──────────────────┐         ┌──────────────────────┐
                │ BlockingQueue<…> │         │  MyThreadEventListener │
                └──────────────────┘         └──────────────────────┘
                       │ take()                      ▲
                       ▼                             │
                ┌──────────────────┐         ┌──────────────────────┐
                │  NetworkThread   │         │ NetworkReceiveThread │
                │    (envoi)       │         │     (réception)      │
                └──────────────────┘         └──────────────────────┘
                       │ send()                      ▲ receive()
                       └──────────────┬──────────────┘
                                      ▼
                              ┌──────────────┐
                              │ DatagramSocket│
                              │  (partagé)    │
                              └──────────────┘
```

### Détail des composants

#### `NetworkThread.java` — thread d'**envoi**
- Hérite de `Thread`.
- Bloque sur `queue.take()` (attente passive, zéro CPU) tant que l'UI ne pousse rien.
- Format attendu dans la queue : `"ip:port:message"` (split sur les 2 premiers `:` uniquement).
- Émet le datagramme UDP via le `DatagramSocket` partagé.
- S'arrête proprement à l'`interrupt()` (sort de `take()` via `InterruptedException`).

#### `NetworkReceiveThread.java` — thread de **réception**
- Hérite de `Thread`.
- Boucle infinie sur `UDPSocket.receive()` (bloquant).
- Définit une interface `MyThreadEventListener` ; à chaque paquet reçu, appelle
  `listener.onEventInMyThread(data)` avec le contenu décodé et `trim()`.
- S'arrête proprement quand on **ferme le socket** depuis l'extérieur : `receive()` lève alors une
  `SocketException` que l'on attrape pour sortir.

#### `MainActivity.java` — orchestration
- Maintient une `BlockingQueue<String>` partagée (`LinkedBlockingQueue`).
- Au clic « Démarrer la Réception » :
  - Crée le `DatagramSocket` bindé sur `0.0.0.0:<port>` (accepte tout paquet entrant).
  - Démarre `NetworkThread` et `NetworkReceiveThread` en leur passant le socket et, pour l'un, la queue,
    pour l'autre, le listener.
- Au clic « Arrêter la Réception » :
  - `threadNetwork.interrupt()` puis `UDPSocket.close()` → les deux threads se terminent proprement.
- Sur les boutons d'envoi (`Envoyer Configuration` / `Actualiser`) :
  - Valide qu'on est en mode IPv4 (`Inet4Address`) pour éviter les soucis d'émulateur dual-stack.
  - Pousse `"ip:port:message"` dans la queue.
- Le listener reçoit les paquets dans un thread non-UI ; il utilise
  `Handler(Looper.getMainLooper()).post(…)` pour mettre à jour `receivedDataTextView` sur le thread UI.

### Pourquoi cette archi ?

| Avantage                                  | Détail                                                                                          |
| ----------------------------------------- | ----------------------------------------------------------------------------------------------- |
| **Séparation des responsabilités**        | L'UI ne touche jamais directement au socket. Chaque thread a un rôle unique et lisible.         |
| **Découplage producteur / consommateur**  | L'UI peut empiler des envois à n'importe quel rythme, le `NetworkThread` les consomme à son rythme. |
| **Attente passive**                       | `BlockingQueue.take()` et `DatagramSocket.receive()` ne consomment **aucun CPU** en attente.    |
| **Réutilisation du socket**               | Un seul socket pour l'envoi et la réception → le serveur peut répondre au port source.          |
| **Pattern Observer**                      | Le listener rend `NetworkReceiveThread` indépendant de l'UI (testable, réutilisable).           |

### Cycle de vie

`onDestroy()` appelle `stopListening()` qui interrompt les threads et ferme le socket : aucune fuite de
ressource au changement d'orientation ou à la fermeture de l'app.

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
   - l'**adresse IP** du serveur :
     - `10.0.2.2` si l'app tourne sur l'**émulateur** Android Studio (alias spécial vers le `localhost` du PC),
     - l'IP locale du PC (ex : `192.168.1.42`) si l'app tourne sur un **téléphone physique** sur le même Wi-Fi.
   - le **port** d'écoute du serveur (par défaut `10000`).
4. Appuyer sur **« Démarrer la Réception »** : l'application crée le socket UDP, démarre les deux threads
   (`NetworkThread` + `NetworkReceiveThread`) et écoute les paquets UDP entrants. Le bouton passe en
   « Arrêter la Réception ».
5. Pour configurer l'ordre d'affichage, saisir une chaîne (ex : `TLH`) puis appuyer sur
   **« Envoyer Configuration »**. La chaîne `ip:port:TLH` est poussée dans la `BlockingQueue` ; le
   `NetworkThread` la consomme et émet le datagramme UDP.
6. Le bouton **« Actualiser les Valeurs »** envoie `getValues()` au serveur ; la réponse s'affiche dans
   la zone « Données reçues ».

### Dépannage rapide

| Symptôme                                     | Cause probable                                                       |
| -------------------------------------------- | -------------------------------------------------------------------- |
| Toast « Démarrez d'abord la réception »      | Tu as cliqué sur Envoyer avant de démarrer l'écoute.                 |
| Log `Envoyé vers …` OK mais serveur muet     | Mauvaise IP : si tu es sur émulateur, utilise `10.0.2.2`, pas `127.0.0.1`. |
| `BindException: Address already in use`      | Le port est déjà utilisé (autre instance, autre app, etc.).          |
| Rien n'arrive dans la zone « Données reçues » | Le serveur ne renvoie pas sur le port source, ou pare-feu PC actif.  |

---

## 9. Permissions

Déclarées dans `AndroidManifest.xml` :

- `android.permission.INTERNET` — nécessaire pour l'émission et la réception UDP.
- `android.permission.ACCESS_NETWORK_STATE` — utile pour vérifier l'état de connectivité du téléphone.

Aucune permission « runtime » n'est demandée à l'utilisateur (toutes les permissions sont de niveau « normal »).
