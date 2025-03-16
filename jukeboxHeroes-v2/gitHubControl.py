import streamlit as st
import time
import requests
import base64
import os
from database import *
from voting_control import *
from results import *
from band_control import *
import shutil

BACKUP_DIR = 'backups/'

# Function to upload the backup to GitHub
def upload_backup_to_github(backup_file):
    # Get GitHub PAT from environment variables
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
    GITHUB_USERNAME = 'az-fkaw'
    GITHUB_REPO = 'Jukebox_LIVE'

    # Prepare the file content (in base64)
    with open(backup_file, 'rb') as file:
        file_content = base64.b64encode(file.read()).decode('utf-8')

    # GitHub API endpoint to upload files
    url = f'https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents/jukeboxHeroes-v2/backups/{os.path.basename(backup_file)}'
    
    # Prepare the headers for authentication
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json'
    }
    
    # Prepare the data payload for the API request
    data = {
        'message': 'Backup SQLite database',
        'content': file_content,
        'branch': 'main',  # Specify the branch you want to push to (e.g., 'main')
    }
    
    # Make the API request to upload the backup
    response = requests.put(url, json=data, headers=headers)
    
    if response.status_code == 201:
        st.success(f'Successfully uploaded the backup to GitHub: {os.path.basename(backup_file)}')
    else:
        st.error(f'Error uploading backup: {response.status_code}')
        st.error(response.json())

# Function to create and upload the database backup
def backup_and_upload():
    # Ensure the backups directory exists
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)  # Create the directory if it doesn't exist
    
    # Make the backup
    timestamp = time.strftime("%Y%m%d%H%M%S")
    backup_file = os.path.join(BACKUP_DIR, f"backup_{timestamp}.db")
    
    # Copy the database to the backup file
    shutil.copy(DATABASE, backup_file)
    
    # Upload the backup to GitHub
    upload_backup_to_github(backup_file)