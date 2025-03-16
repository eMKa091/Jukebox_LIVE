import os 
import requests
import base64

BACKUP_DIR = 'backups/'
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USERNAME = 'az-fkaw'
GITHUB_REPO = 'Jukebox_LIVE'
BACKUP_FOLDER = 'jukeboxHeroes-v2/backups'
DB_PATH = 'votes.db'

def download_database_from_github():
    # URL to access the GitHub content
    url = f'https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents/{BACKUP_FOLDER}/{DB_PATH}?ref=main'
    
    headers = {'Authorization': f'token {GITHUB_TOKEN}'}
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        # Get the database file content (base64 encoded)
        file_content = response.json()['content']
        
        # Log the first 100 characters of the content to debug
        print(f"File content (Base64): {file_content[:100]}...")

        # Clean up the base64 string (remove any newlines or spaces)
        cleaned_content = file_content.replace("\n", "").replace("\r", "")
        
        # Decode the cleaned content from base64 and save it locally
        with open(DB_PATH, 'wb') as f:
            f.write(base64.b64decode(cleaned_content))
        print(f"Database downloaded from GitHub: {DB_PATH}")
    else:
        print(f"Failed to download database from GitHub: {response.status_code}")