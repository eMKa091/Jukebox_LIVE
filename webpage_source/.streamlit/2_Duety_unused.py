# Import of needed packages and their aliases
import streamlit as st
import pandas as pd
import os

# General page configuration
st.set_page_config(page_title='Duety')

############################
# Check if uniqueID is set #
############################
# uniqueID is inherited from the main page (user input) through session state
# Until uniqueID is not specifed, user gets nowhere
if "uniqueID" not in st.session_state:
    st.warning("Prosím zadejte přezdívku na úvodní stránce!")
    st.stop()

uniqueID = st.session_state.uniqueID
randomizer = st.session_state.randomNumber

#################################################
# Initialize global variables for each category #
#################################################
if "selected_indices" not in st.session_state:
    st.session_state.selected_indices = {}

if "Duety" not in st.session_state.selected_indices:
    st.session_state.selected_indices["Duety"] = []

############################
#   Source data handling   #
############################
# Data path
csvDuetyPath = "./dataSources/duety.csv"

@st.cache_data
def load_duets_data(path):
    df = pd.read_csv(path)
    return df

duetsDF = load_duets_data(csvDuetyPath)

############################
#   User interface build   #
############################
############################
# Dropdown navigation menu #
############################
st.divider()
st.info('Prosím vyberte písně (celkově maximálně 10 napříč všemi kategoriemi)')
st.divider()

# Calculate total initially selected songs for all categories
total_selected = sum(len(indices) for indices in st.session_state.selected_indices.values())

# Display checkboxes and update selected indices for given category
for index, row in duetsDF.iterrows():
    selected = index in st.session_state.selected_indices["Duety"]
    disabled = False
    if total_selected >= 10 and not selected:
        disabled = True
    selected = st.checkbox(f"{row['Umelec']} - {row['Pisen']}", value=selected, disabled=disabled, key=f"checkbox_{index}")
    if selected and index not in st.session_state.selected_indices["Duety"]:
        st.session_state.selected_indices["Duety"].append(index)
        total_selected += 1  # Increment total selected count
    elif not selected and index in st.session_state.selected_indices["Duety"]:
        st.session_state.selected_indices["Duety"].remove(index)
        total_selected -= 1  # Decrement total selected count

# Label for the progress bar
progress_label = f"Celkem vybráno {total_selected} z 10 písní"

# Progress bar with a target of 10 total songs
progress = min(total_selected / 10, 1.0)
st.progress(progress)
st.text(progress_label)

# Button to send selected songs list
if st.button("Uložit výběr z dané kategorie"):
    # Use uniqueID and random number to generate unique filename
    file_name = f"selected_songs_duety_{uniqueID}-{randomizer}.txt"
    
    # Construct file path
    file_path = os.path.join("webpage_source", "vote_results", file_name)
    
    # Write selected songs to the file
    with open(file_path, "w") as file:
        for index in st.session_state.selected_indices["Duety"]:
            file.write(f"{duetsDF.iloc[index]['Pisen']} od {duetsDF.iloc[index]['Umelec']}\n")
    
    # Show success message
    st.success("Výběr písní z dané kategorie byl uložen!")
