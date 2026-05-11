# Lit le fichier schema_base.sql et l'exécute pour créer la base de données SQLite avec les trois tables.
import sqlite3
import os

DB_FILE = "iot_project.db" # Le nom du fichier de base de données qui sera créé
SQL_FILE = "schema_base.sql" # Le fichier qui contient les instructions SQL pour créer les tables.

def build_database():
    print(f"[*] Initialisation de la base de données : {DB_FILE}...")
    
    # Vérifie si le fichier SQL existe (sinon on s'arrête et on affiche une erreur)
    if not os.path.exists(SQL_FILE): 
        print(f"[ERREUR] Le fichier {SQL_FILE} est introuvable dans le dossier.")
        return

    # Ouverture fichier sql et Lecture des instructions SQL
    with open(SQL_FILE, 'r', encoding='utf-8') as f:
        sql_script = f.read()

    # Connexion et exécution
    conn = sqlite3.connect(DB_FILE) # Crée la connexion à la base. Si le fichier iot_project.db existe pas alors créer automatiquement
    cursor = conn.cursor() # Crée un curseur pour pouvoir exécuter des requêtes.
    cursor.executescript(sql_script) # Execute tout le contenu du fichier sql d'un coup
    conn.commit() # Sauvegarde les changements dans la base.
    conn.close() # Ferme la connexion proprement.
    
    print("[+] Base de données créée avec succès avec la nouvelle structure !")

if __name__ == "__main__": # Lance la fonction uniquement si on exécute directement setup_db.py 
    build_database()