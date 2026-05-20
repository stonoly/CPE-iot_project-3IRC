# Grafana — CPE IoT Project

Dashboard pour visualiser en temps réel les mesures des capteurs
(température, humidité, pression, luminosité).

### Prérequis
- Docker & Docker Compose installés

### Structure
```
grafana-iot/
├── docker-compose.yml
├── data/
│   └── iot_project.db          ← Base SQLite à copier depuis serveur/
├── grafana/
│   ├── provisioning/
│   │   ├── datasources/
│   │   │   └── sqlite.yaml     ← Datasource SQLite auto-configurée
│   │   └── dashboards/
│   │       └── dashboards.yaml
│   └── dashboards/
│       └── iot-dashboard.json  ← Dashboard principal
└── README.md
```

## Lancement

```bash
# 1. Copier la base SQLite depuis le serveur
cp ../serveur/iot_project.db ./data/iot_project.db

# 2. Démarrer Grafana
docker compose up -d
```

Ouvrir **http://localhost:3000** — login : `admin` / `admin`

Le dashboard ne se charge pas toujours automatiquement selon la version de Grafana.
Si la page Dashboards est vide, faire :
**Dashboards → New → Import → Upload JSON file** et sélectionner `grafana/dashboards/iot-dashboard.json`.

---

## Panels

| Panel | Type | Contenu |
|-------|------|---------|
| Température | Time series | Évolution en °C |
| Humidité | Time series | Humidité relative en % |
| Luminosité | Time series | Luminosité en lux |
| Pression | Time series | Pression en hPa |
| Gauges (×4) | Gauge | Dernière valeur de chaque capteur |
| Historique | Table | 50 dernières mesures |
| Modules | Table | Capteurs enregistrés en base |
| Stats | Stat | Moyennes globales |

---

## Synchronisation en temps réel

Le dashboard se rafraîchit toutes les **5 secondes**.
Pour que les données suivent ce que reçoit le serveur, il faut copier
la base régulièrement pendant que `controller.py` tourne :

```bash
# Linux / WSL
watch -n 5 cp ../serveur/iot_project.db ./data/iot_project.db

# Windows PowerShell
while ($true) {
    Copy-Item "..\serveur\iot_project.db" ".\data\iot_project.db" -Force
    Start-Sleep 5
}
```

---

## Arrêt

```bash
docker compose down

# Pour supprimer aussi les volumes (repart de zéro au prochain lancement)
docker compose down -v
```