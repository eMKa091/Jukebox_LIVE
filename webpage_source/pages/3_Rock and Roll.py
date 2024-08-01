# Import needed packages and their aliases
import streamlit as st
import pandas as pd
import importlib
import os
from streamlit_navigation_bar import st_navbar

# General page configuration
st.set_page_config(page_title="Rock and roll", initial_sidebar_state='collapsed')

def RockAndRoll():
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

    st.info('Prosím vyberte písně (celkově maximálně 25 napříč všemi kategoriemi)')

    #################################################
    # Initialize global variables for each category #
    #################################################
    if "selected_indices" not in st.session_state:
        st.session_state.selected_indices = {}

    if "Rokenrol" not in st.session_state.selected_indices:
        st.session_state.selected_indices["Rokenrol"] = []

    ############################
    #   Source data handling   #
    ############################
    # Data path
    csvRokenrolPath = "./dataSources/rokenrol.csv"

    @st.cache_data
    def load_rr_data(path):
        df = pd.read_csv(path)
        return df

    rokenrolDF = load_rr_data(csvRokenrolPath)

    ############################
    #   User interface build   #
    ############################
    # Define the navigation options
    nav_options = ["České písně", "Duety"]

    # Create the navigation bar
    selected_page = st_navbar(nav_options)
    st.divider()

    # Load the selected page content using importlib
    if selected_page == "České písně":
        duety_module = importlib.import_module('pages.1_České písně')
        duety_module.ceskePisne()
    elif selected_page == "Duety":
        rock_and_roll_module = importlib.import_module('pages.2_Duety')
        rock_and_roll_module.Duety()
        
    st.divider()
    st.info('Prosím vyberte písně (celkově maximálně 25 napříč všemi kategoriemi)')
    st.divider()

    # Calculate total initially selected songs for all categories
    total_selected = sum(len(indices) for indices in st.session_state.selected_indices.values())

    # Display checkboxes and update selected indices for given category
    for index, row in rokenrolDF.iterrows():
        selected = index in st.session_state.selected_indices["Rokenrol"]
        disabled = False
        if total_selected >= 25 and not selected:
            disabled = True
        selected = st.checkbox(f"{row['Umelec']} - {row['Pisen']}", value=selected, disabled=disabled, key=f"checkbox_{index}")
        if selected and index not in st.session_state.selected_indices["Rokenrol"]:
            st.session_state.selected_indices["Rokenrol"].append(index)
            total_selected += 1  # Increment total selected count
        elif not selected and index in st.session_state.selected_indices["Rokenrol"]:
            st.session_state.selected_indices["Rokenrol"].remove(index)
            total_selected -= 1  # Decrement total selected count

    # Label for the progress bar
    progress_label = f"Celkem vybráno {total_selected} z 25 písní"

    # Progress bar with a target of 25 total songs
    progress = min(total_selected / 25, 1.0)
    st.progress(progress)
    st.text(progress_label)

    # Button to send selected songs list
    if st.button("Uložit výběr z dané kategorie"):
        # Use uniqueID and random number to generate unique filename
        file_name = f"selected_songs_rokenrol_{uniqueID}-{randomizer}.txt"
        
        # Construct file path
        file_path = os.path.join("webpage_source", "vote_results", file_name)
        
        # Write selected songs to the file
        with open(file_path, "w") as file:
            for index in st.session_state.selected_indices["Rokenrol"]:
                file.write(f"{rokenrolDF.iloc[index]['Pisen']} od {rokenrolDF.iloc[index]['Umelec']}\n")
        
        # Show success message
        st.success("Výběr písní z dané kategorie byl uložen!")