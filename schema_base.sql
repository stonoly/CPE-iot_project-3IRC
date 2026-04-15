DROP TABLE IF EXISTS Module_IoT;
DROP TABLE IF EXISTS Historique_Donnees;
DROP TABLE IF EXISTS Journal_Trafic;

-- Table pour enregistrer les différents objets (Micro:bits)
CREATE TABLE IF NOT EXISTS Module_IoT (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    id_reseau TEXT UNIQUE,
    emplacement TEXT DEFAULT 'Bureau',
    usage_piece TEXT DEFAULT 'Bureau',
    format_affichage TEXT
);

-- Table pour l'historique des relevés météo
CREATE TABLE IF NOT EXISTS Historique_Donnees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id INTEGER,
    horodatage DATETIME DEFAULT CURRENT_TIMESTAMP,
    val_temp REAL,
    val_lum REAL,
    val_hum REAL,
    val_pres REAL,
    FOREIGN KEY(module_id) REFERENCES Module_IoT(id)
);

-- Table pour conserver une trace de toutes les communications
CREATE TABLE IF NOT EXISTS Journal_Trafic (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    horodatage DATETIME DEFAULT CURRENT_TIMESTAMP,
    canal TEXT,
    sens_flux TEXT,
    infos_source TEXT,
    payload_brut TEXT
);