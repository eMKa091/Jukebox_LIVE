import streamlit as st
import requests
import base64
import os
from database import *
from voting_control import *
from results import *
from band_control import *
import shutil
import urllib.parse

BACKUP_DIR = 'jukeboxHeroes-v2/backups/'
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USERNAME = 'az-fkaw'
GITHUB_REPO = 'Jukebox_LIVE'
BACKUP_FOLDER = 'jukeboxHeroes-v2/backups'  # Correct GitHub backup folder
DB_PATH = 'votes.db'  # Original database path (not backup-votes.db)

# Ensure the backup directory exists locally
if not os.path.exists(BACKUP_DIR):
    os.makedirs(BACKUP_DIR)  # Create the directory if it doesn't exist

# Function to get the sha of an existing file from GitHub
def get_file_sha_from_github():
    url = f'https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents/{urllib.parse.quote(BACKUP_FOLDER)}/{urllib.parse.quote("backup-votes.db")}'
    
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json'
    }
    
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        # The sha of the existing file
        return response.json()['sha']
    else:
        return None  # If file doesn't exist, we return None

# Function to upload the backup to GitHub
def upload_backup_to_github(backup_file):
    # Prepare the file content (in base64)
    with open(backup_file, 'rb') as file:
        file_content = base64.b64encode(file.read()).decode('utf-8')

    # URL-encode the backup file path
    encoded_backup_folder = urllib.parse.quote(BACKUP_FOLDER)
    encoded_file_name = urllib.parse.quote(os.path.basename(backup_file))

    # Get the sha of the existing file (if it exists)
    sha = get_file_sha_from_github()

    # GitHub API endpoint to upload files
    url = f'https://api.github.com/repos/{GITHUB_USERNAME}/{GITHUB_REPO}/contents/{encoded_backup_folder}/{encoded_file_name}'
    
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

    # If the file exists, we need to include the sha in the request to overwrite the file
    if sha:
        data['sha'] = sha  # Add the sha if the file exists

    # Make the API request to upload the backup
    response = requests.put(url, json=data, headers=headers)
    
    if response.status_code == 201:
        st.success(f'Successfully uploaded the backup to GitHub: {os.path.basename(backup_file)}')
    elif response.status_code == 200:
        st.success(f'Successfully updated the backup on GitHub: {os.path.basename(backup_file)}')
    else:
        st.error(f'Error uploading backup: {response.status_code}')
        st.error(response.json())

# Function to create and upload the database backup
# Ensure the backups directory exists before copying the file
def backup_and_upload():
    # Ensure the backups directory exists locally
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)  # Create the directory if it doesn't exist

    # Generate the backup file path under the backups directory
    backup_file = os.path.join(BACKUP_DIR, "backup-votes.db")  # Corrected backup file path

    # Check if the original database file exists before attempting to copy
    if not os.path.exists(DB_PATH):
        return

    # Copy the original database to the backup file
    shutil.copy(DB_PATH, backup_file)
    
    # Upload the backup to GitHub
    upload_backup_to_github(backup_file)