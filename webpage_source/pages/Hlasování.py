# Import of needed packages and their aliases
import streamlit as st
import pandas as pd
import sqlite3
from random import randint
from datetime import datetime

# General page configuration
st.set_page_config(page_title='Hlasovani')

############################
# Check if uniqueID is set #
############################
# uniqueID is inherited from the main page (user input) through session state
# Until uniqueID is not specified, user gets nowhere
if "uniqueID" not in st.session_state:
    st.warning("Prosím zadejte přezdívku na úvodní stránce!")
    st.stop()

uniqueID = st.session_state.uniqueID
randomizer = st.session_state.randomNumber
randomNumber = randint(1, 100)

#################################################
# Initialize global variables for each category #
#################################################
if "selected_indices" not in st.session_state:
    st.session_state.selected_indices = {}

if "Songs" not in st.session_state.selected_indices:
    st.session_state.selected_indices["Songs"] = []

if "modal_shown" not in st.session_state:
    st.session_state.modal_shown = False

############################
#   Source data handling   #
############################
# Data path
csvSongsPath = "./dataSources/songList.csv"

# Cache dataframe for better performance
@st.cache_data
def load_songs_data(path):
    df = pd.read_csv(path)
    return df

songsDF = load_songs_data(csvSongsPath)

######
# DB #
######
# Function to initialize the database
def init_db():
    conn = sqlite3.connect('votes.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS votes (
            uniqueID TEXT,
            randomNumber INTEGER,
            song TEXT,
            date TEXT
        )
    ''')
    conn.commit()
    conn.close()

# Function to save votes to the database
def save_vote(uniqueID, randomNumber, song):
    conn = sqlite3.connect('votes.db')
    c = conn.cursor()
    date_today = datetime.now().strftime('%Y-%m-%d')  # Format as YYYY-MM-DD
    c.execute('''
        INSERT INTO votes (uniqueID, randomNumber, song, date)
        VALUES (?, ?, ?, ?)
    ''', (uniqueID, randomNumber, song, date_today))
    conn.commit()
    conn.close()

############################
#   User interface build   #
############################
st.divider()
st.info('Vyber svých 10 nejvíce oblíbených songů!')
st.divider()
# Initialize the database
init_db()

# Calculate total initially selected songs for all categories
total_selected = sum(len(indices) for indices in st.session_state.selected_indices.values())

# Display checkboxes and update selected indices for given category
for index, row in songsDF.iterrows():
    selected = index in st.session_state.selected_indices["Songs"]
    disabled = False
    if total_selected >= 10 and not selected:
        disabled = True
    selected = st.checkbox(f"{row['Author']} - {row['Song']}", value=selected, disabled=disabled, key=f"checkbox_{index}")
    if selected and index not in st.session_state.selected_indices["Songs"]:
        st.session_state.selected_indices["Songs"].append(index)
        total_selected += 1  # Increment total selected count
    elif not selected and index in st.session_state.selected_indices["Songs"]:
        st.session_state.selected_indices["Songs"].remove(index)
        total_selected -= 1  # Decrement total selected count

# Label for the progress bar below
progress_label = f"Celkem vybráno {total_selected} z 10 písní"

# Progress bar with a target of 10 total songs
progress = min(total_selected / 10, 1.0)
st.progress(progress)
st.text(progress_label)

##############################
# Save the selection to file #
##############################
if st.button("Odeslat výběr"):
    conn = sqlite3.connect('votes.db')
    c = conn.cursor()
    for index in st.session_state.selected_indices["Songs"]:
        song = f"{songsDF.iloc[index]['Author']} - {songsDF.iloc[index]['Song']}"
        save_vote(uniqueID, randomNumber, song)
    conn.close()
    st.success("Tvůj výběr byl uložen, děkujeme!")
    st.balloons()