import streamlit as st
import pandas as pd
import os
from datetime import datetime

st.set_page_config(page_title='České písně')

# Check if uniqueID is set
if "uniqueID" not in st.session_state:
    st.warning("Prosím zadejte přezdívku na úvodní stránce!")
    st.stop()

uniqueID = st.session_state.uniqueID

st.info('Prosím vyberte písně (celkově maximálně 25 napříč všemi kategoriemi)')

# Initialize global variables for each category
if "selected_indices" not in st.session_state:
    st.session_state.selected_indices = {}

if "Ceske" not in st.session_state.selected_indices:
    st.session_state.selected_indices["Ceske"] = []

# Load data
csvCeskePath = "./dataSources/ceske.csv"

@st.cache_data
def load_ceske_data(path):
    df = pd.read_csv(path)
    return df

ceskeDF = load_ceske_data(csvCeskePath)

# Display checkboxes and update selected indices for České písně category
for index, row in ceskeDF.iterrows():
    selected = index in st.session_state.selected_indices["Ceske"]
    selected = st.checkbox(f"{row['Umelec']} - {row['Pisen']}", value=selected, key=f"checkbox_{index}")
    if selected and index not in st.session_state.selected_indices["Ceske"]:
        st.session_state.selected_indices["Ceske"].append(index)
    elif not selected and index in st.session_state.selected_indices["Ceske"]:
        st.session_state.selected_indices["Ceske"].remove(index)

# Calculate total selected songs for all categories
total_selected = sum(len(indices) for indices in st.session_state.selected_indices.values())

# Label for the progress bar
progress_label = f"Celkem vybráno {total_selected} z 25 písní"

# Progress bar with a target of 25 total songs
progress = min(total_selected / 25, 1.0)
st.progress(progress)
st.text(progress_label)

if st.button("Odeslat vybrané písně z dané kategorie"):
    # Use uniqueID to generate unique filename
    file_name = f"selected_songs_ceske_{uniqueID}.txt"
    
    # Construct file path
    file_path = os.path.join("webpage_source", "vote_results", file_name)
    
    # Write selected songs to the file
    with open(file_path, "w") as file:
        for index in st.session_state.selected_indices["Ceske"]:
            file.write(f"{ceskeDF.iloc[index]['Pisen']} od {ceskeDF.iloc[index]['Umelec']}\n")
    
    # Show success message
    st.success("Vybrané písně byly odeslány!")
