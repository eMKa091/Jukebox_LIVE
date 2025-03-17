import os 
import requests
import base64
import sqlite3

BACKUP_DIR = 'backups/'
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USERNAME = 'az-fkaw'
GITHUB_REPO = 'Jukebox_LIVE'
BACKUP_FOLDER = 'jukeboxHeroes-v2/backups'
DB_PATH = 'votes.db'

def check_db_validity():
    if not os.path.exists(DB_PATH):
        print("Database does not exist.")
        return False
    
    # Check if the events table exists
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='events';")
        table_exists = cursor.fetchone() is not None
        conn.close()
        return table_exists
    except sqlite3.Error as e:
        print(f"Error checking database: {e}")
        return False

def download_database_from_github():
    # URL to access the GitHub content
    url = f'https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents/{BACKUP_FOLDER}/{DB_PATH}?ref=main'
    
    headers = {'Authorization': f'token {GITHUB_TOKEN}'}
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        file_content = response.json()['content']
        
        if not file_content:
            print("Error: The file content is empty.")
            return
        
        cleaned_content = file_content.replace("\n", "").replace("\r", "")
        
        # Write the content to the database file
        with open(DB_PATH, 'wb') as f:
            f.write(base64.b64decode(cleaned_content))
        print(f"Database downloaded from GitHub: {DB_PATH}")
        
        # Check if the file is valid
        if not check_db_validity():
            print("Error: Database is empty or corrupted.")
            return
        
        print(f"Database is valid and ready.")
    else:
        print(f"Failed to download database from GitHub: {response.status_code}")