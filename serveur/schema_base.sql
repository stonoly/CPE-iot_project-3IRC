-- Définit la structure de la base de données — les 3 tables qui stockent les capteurs, les mesures et les communications.

-- Supprime les tables si elles existent déjà. Utile quand on relance setup_db.py pour repartir d'une base propre.

DROP TABLE IF EXISTS Journal_Trafic;
DROP TABLE IF EXISTS Historique_Donnees;
DROP TABLE IF EXISTS Module_IoT;

-- Table pour enregistrer les différents objets (Micro:bits capteurs), Stocke les capteurs enregistrés.
CREATE TABLE IF NOT EXISTS Module_IoT (
    id                INTEGER PRIMARY KEY AUTOINCREMENT, -- Identifiant unique généré automatiquement par SQLite à chaque insertion.
    num_capteur       INTEGER UNIQUE,          -- Numéro logique du capteur (1, 2, 3...). UNIQUE empêche deux capteurs d'avoir le même numéro.
    id_reseau         TEXT UNIQUE,             -- Nom réseau du capteur, ex: "capteur_1". Aussi unique
    emplacement       TEXT DEFAULT 'Bureau',   -- Localisation du capteur. DEFAULT signifie que si on ne précise pas de valeur
    usage_piece       TEXT DEFAULT 'Bureau',   --  'Bureau' est utilisé automatiquement.
    format_affichage  TEXT DEFAULT 'TLHP'      -- Ordre d'affichage par défaut sur l'écran OLED.
);

-- Table pour l'historique des relevés, Stocke toutes les mesures reçues.
CREATE TABLE IF NOT EXISTS Historique_Donnees (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id   INTEGER NOT NULL, -- Référence le capteur qui a envoyé la mesure. 
    horodatage  DATETIME DEFAULT CURRENT_TIMESTAMP, -- Date et heure de la mesure. Si on ne précise rien, SQLite met l'heure actuelle automatiquement.
    val_temp    REAL, -- Les quatre valeurs capteurs stockées en nombre décimal (REAL).
    val_lum     REAL,
    val_hum     REAL,
    val_pres    REAL,
    ts_unix     INTEGER, -- Timestamp Unix (nb secondes depuis le 1er janvier 1970).
                         -- Ajouté car le format horodatage UTC n'est pas reconnu par le plugin SQLite de Grafana
                         -- pour afficher les courbes sur un axe temporel.
    FOREIGN KEY(module_id) REFERENCES Module_IoT(id) -- Lie chaque mesure à un capteur dans Module_IoT. Si le capteur existe pas, l'insertion est refusée.
);

-- Table pour tracer toutes les communications
CREATE TABLE IF NOT EXISTS Journal_Trafic (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    horodatage   DATETIME DEFAULT CURRENT_TIMESTAMP,
    canal        TEXT,       -- "UART" ou "UDP" selon le type de communication.
    sens_flux    TEXT,       -- "RX" si le message a été reçu, "TX" s'il a été envoyé.
    infos_source TEXT,       -- L'adresse ou le port source du message.
    payload_brut TEXT        -- Le contenu brut du message tel qu'il a été reçu ou envoyé.
);