# Import of needed packages and their aliases
import streamlit as st
import pandas as pd
import os

# General page configuration
st.set_page_config(page_title='České písně')

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

############################
#   User interface build   #
############################
st.divider()
st.info('Vyber svých 10 nejvíce oblíbených songů!')
st.divider()

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
    # Use uniqueID and random number to generate unique filename
    file_name = f"selected_songs_{uniqueID}-{randomizer}.txt"
    
    # Construct file path
    file_path = os.path.join("webpage_source", "vote_results", file_name)
    
    # Write selected songs to the file
    with open(file_path, "w") as file:
        for index in st.session_state.selected_indices["Songs"]:
            file.write(f"{songsDF.iloc[index]['Author']} - {songsDF.iloc[index]['Song']}\n")
    
    # Show success message
    st.success("Tvůj výběr byl uložen, děkujeme!")
    st.balloons()