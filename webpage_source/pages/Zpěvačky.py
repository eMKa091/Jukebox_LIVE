import streamlit as st
import pandas as pd

st.set_page_config(page_title='Ženy')

# Initialize global variables for each category
if "selected_indices" not in st.session_state:
    st.session_state.selected_indices = {}

if "Zpevacky" not in st.session_state.selected_indices:
    st.session_state.selected_indices["Zpevacky"] = []

# Caching data for faster loading
csvZenyPath = "./dataSources/zeny.csv"

@st.cache_data
def load_female_data(path):
    df = pd.read_csv(path)
    return df

zenyDF = load_female_data(csvZenyPath)

# Display checkboxes and update selected indices for Zpevacky category
for index, row in zenyDF.iterrows():
    selected = index in st.session_state.selected_indices["Zpevacky"]
    selected = st.checkbox(f"{row['Pisen']} od {row['Umelec']}", value=selected, key=f"checkbox_{index}")
    if selected and index not in st.session_state.selected_indices["Zpevacky"]:
        st.session_state.selected_indices["Zpevacky"].append(index)
    elif not selected and index in st.session_state.selected_indices["Zpevacky"]:
        st.session_state.selected_indices["Zpevacky"].remove(index)

# Calculate total selected songs for all categories
total_selected = sum(len(indices) for indices in st.session_state.selected_indices.values())

# Label for the progress bar
progress_label = f"Celkem vybráno {total_selected} z 25 písní"

# Progress bar with a target of 25 total songs
progress = min(total_selected / 25, 1.0)
st.progress(progress)
st.text(progress_label)