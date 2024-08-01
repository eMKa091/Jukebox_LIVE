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

if "Ceske" not in st.session_state.selected_indices:
    st.session_state.selected_indices["Ceske"] = []

############################
#   Source data handling   #
############################
# Data path
csvCeskePath = "./dataSources/ceske.csv"

# Cache dataframe for better performance
@st.cache_data
def load_ceske_data(path):
    df = pd.read_csv(path)
    return df

ceskeDF = load_ceske_data(csvCeskePath)

############################
#   User interface build   #
############################
st.divider()
st.info('Prosím vyberte písně (celkově maximálně 25 napříč všemi kategoriemi)')
st.divider()

# Calculate total initially selected songs for all categories
total_selected = sum(len(indices) for indices in st.session_state.selected_indices.values())

# Display checkboxes and update selected indices for given category
for index, row in ceskeDF.iterrows():
    selected = index in st.session_state.selected_indices["Ceske"]
    disabled = False
    if total_selected >= 25 and not selected:
        disabled = True
    selected = st.checkbox(f"{row['Umelec']} - {row['Pisen']}", value=selected, disabled=disabled, key=f"checkbox_{index}")
    if selected and index not in st.session_state.selected_indices["Ceske"]:
        st.session_state.selected_indices["Ceske"].append(index)
        total_selected += 1  # Increment total selected count
    elif not selected and index in st.session_state.selected_indices["Ceske"]:
        st.session_state.selected_indices["Ceske"].remove(index)
        total_selected -= 1  # Decrement total selected count

# Label for the progress bar below
progress_label = f"Celkem vybráno {total_selected} z 25 písní"

# Progress bar with a target of 25 total songs
progress = min(total_selected / 25, 1.0)
st.progress(progress)
st.text(progress_label)
if total_selected == 25:
    st.balloons
    st.stop
    st.success("Dekujeme za vas vyber")

##############################
# Save the selection to file #
##############################
if st.button("Uložit výběr z dané kategorie"):
    # Use uniqueID and random number to generate unique filename
    file_name = f"selected_songs_ceske_{uniqueID}-{randomizer}.txt"
    
    # Construct file path
    file_path = os.path.join("webpage_source", "vote_results", file_name)
    
    # Write selected songs to the file
    with open(file_path, "w") as file:
        for index in st.session_state.selected_indices["Ceske"]:
            file.write(f"{ceskeDF.iloc[index]['Umelec']} - {ceskeDF.iloc[index]['Pisen']}\n")
    
    # Show success message
    st.success("Výběr písní z dané kategorie byl uložen!")