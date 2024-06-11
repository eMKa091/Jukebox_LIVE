import streamlit as st
import pandas as pd
import os

st.set_page_config(page_title='Rock and roll')

# Initialize global variables for each category
if "selected_indices" not in st.session_state:
    st.session_state.selected_indices = {}

if "Rokenrol" not in st.session_state.selected_indices:
    st.session_state.selected_indices["Rokenrol"] = []

# Load data
csvRokenrolPath = "./dataSources/rokenrol.csv"

@st.cache_data
def load_rr_data(path):
    df = pd.read_csv(path)
    return df

rokenrolDF = load_rr_data(csvRokenrolPath)

# Display checkboxes and update selected indices for Rokenrol category
for index, row in rokenrolDF.iterrows():
    selected = index in st.session_state.selected_indices["Rokenrol"]
    selected = st.checkbox(f"{row['Umelec']} - {row['Pisen']}", value=selected, key=f"checkbox_{index}")
    if selected and index not in st.session_state.selected_indices["Rokenrol"]:
        st.session_state.selected_indices["Rokenrol"].append(index)
    elif not selected and index in st.session_state.selected_indices["Rokenrol"]:
        st.session_state.selected_indices["Rokenrol"].remove(index)

# Calculate total selected songs for all categories
total_selected = sum(len(indices) for indices in st.session_state.selected_indices.values())

# Label for the progress bar
progress_label = f"Celkem vybráno {total_selected} z 25 písní"

# Progress bar with a target of 25 total songs
progress = min(total_selected / 25, 1.0)
st.progress(progress)
st.text(progress_label)

# Button to send selected songs list
if st.button("Odeslat vybrané písně z dané kategorie"):
    current_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(current_dir, "../../webpage_source/vote_results/selected_songs_rokenrol.txt")
    with open(file_path, "w") as file:
        for index in st.session_state.selected_indices["Rokenrol"]:
            file.write(f"{rokenrolDF.iloc[index]['Pisen']} od {rokenrolDF.iloc[index]['Umelec']}\n")
    st.success("Vybrané písně byly odeslány!")