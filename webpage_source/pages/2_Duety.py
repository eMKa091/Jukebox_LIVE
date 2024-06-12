import streamlit as st
import pandas as pd
import os

st.set_page_config(page_title='Duety')

# Check if uniqueID is set
if "uniqueID" not in st.session_state:
    st.warning("Prosím zadejte přezdívku na úvodní stránce!")
    st.stop()

uniqueID = st.session_state.uniqueID

st.info('Prosím vyberte písně (celkově maximálně 25 napříč všemi kategoriemi)')

# Initialize global variables for each category
if "selected_indices" not in st.session_state:
    st.session_state.selected_indices = {}

if "Duety" not in st.session_state.selected_indices:
    st.session_state.selected_indices["Duety"] = []

# Load data
csvDuetyPath = "./dataSources/duety.csv"

@st.cache_data
def load_duets_data(path):
    df = pd.read_csv(path)
    return df

duetsDF = load_duets_data(csvDuetyPath)

# Display checkboxes and update selected indices for Duety category
for index, row in duetsDF.iterrows():
    selected = index in st.session_state.selected_indices["Duety"]
    selected = st.checkbox(f"{row['Umelec']} - {row['Pisen']}", value=selected, key=f"checkbox_{index}")
    if selected and index not in st.session_state.selected_indices["Duety"]:
        st.session_state.selected_indices["Duety"].append(index)
    elif not selected and index in st.session_state.selected_indices["Duety"]:
        st.session_state.selected_indices["Duety"].remove(index)

# Calculate total selected songs for all categories
total_selected = sum(len(indices) for indices in st.session_state.selected_indices.values())

# Label for the progress bar
progress_label = f"Celkem vybráno {total_selected} z 25 písní"

# Progress bar with a target of 25 total songs
progress = min(total_selected / 25, 1.0)
st.progress(progress)
st.text(progress_label)

# Button to send selected songs list
if st.button("Uložit výběr z dané kategorie"):
    # Use uniqueID to generate unique filename
    file_name = f"selected_songs_duety_{uniqueID}.txt"
    
    # Construct file path
    file_path = os.path.join("webpage_source", "vote_results", file_name)
    
    # Write selected songs to the file
    with open(file_path, "w") as file:
        for index in st.session_state.selected_indices["Duety"]:
            file.write(f"{duetsDF.iloc[index]['Pisen']} od {duetsDF.iloc[index]['Umelec']}\n")
    
    # Show success message
    st.success("Výběr písní z dané kategorie byl uložen!")
