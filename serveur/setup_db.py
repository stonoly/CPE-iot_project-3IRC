import sqlite3
import os

DB_FILE = "iot_project.db"
SQL_FILE = "schema_base.sql"

def build_database():
    print(f"[*] Initialisation de la base de données : {DB_FILE}...")
    
    # Vérifie si le fichier SQL existe
    if not os.path.exists(SQL_FILE):
        print(f"[ERREUR] Le fichier {SQL_FILE} est introuvable dans le dossier.")
        return

    # Lecture des instructions SQL
    with open(SQL_FILE, 'r', encoding='utf-8') as f:
        sql_script = f.read()

    # Connexion et exécution
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.executescript(sql_script)
    conn.commit()
    conn.close()
    
    print("[+] Base de données créée avec succès avec la nouvelle structure !")

if __name__ == "__main__":
    build_database()