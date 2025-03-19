import os 
import requests
import base64

BACKUP_FILE = './backups/backup-votes.db'
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USERNAME = 'az-fkaw'
GITHUB_REPO = 'Jukebox_LIVE'
BACKUP_FOLDER = 'jukeboxHeroes-v2/backups'

def download_database_from_github():
    """Downloads the database backup from GitHub."""
    url = f'https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents/{BACKUP_FOLDER}/backup-votes.db?ref=main'
    print(f"Attempting to download database from GitHub: {url}")
    
    headers = {'Authorization': f'token {GITHUB_TOKEN}'}
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        print("Successfully fetched database content from GitHub.")
        file_content = response.json().get('content', '')
        
        if not file_content:
            print("Error: The file content is empty.")
            return
        
        # Clean up the file content by removing newline characters (if any)
        cleaned_content = file_content.replace("\n", "").replace("\r", "")
        
        # Ensure the backup directory exists
        os.makedirs(os.path.dirname(BACKUP_FILE), exist_ok=True)

        # Decode the base64 content and write to the backup file
        try:
            decoded_content = base64.b64decode(cleaned_content)
            with open(BACKUP_FILE, 'wb') as f:
                f.write(decoded_content)
            print(f"Database downloaded and saved to {BACKUP_FILE}")
        except Exception as e:
            print(f"Error decoding or writing the file: {e}")
    else:
        print(f"Failed to download database from GitHub. Status Code: {response.status_code}")
        print(response.json())