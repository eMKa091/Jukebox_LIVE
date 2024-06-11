import streamlit as st
import pandas as pd

st.set_page_config(page_title='Muži')

# Initialize global variables for each category
if "selected_indices" not in st.session_state:
    st.session_state.selected_indices = {}

if "Zpevaci" not in st.session_state.selected_indices:
    st.session_state.selected_indices["Zpevaci"] = []

# Caching data for faster loading
csvMuziPath = "./dataSources/muzi.csv"

@st.cache_data
def load_male_data(path):
    df = pd.read_csv(path)
    return df

muziDF = load_male_data(csvMuziPath)

# Display checkboxes and update selected indices for Zpevaci category
for index, row in muziDF.iterrows():
    selected = index in st.session_state.selected_indices["Zpevaci"]
    selected = st.checkbox(f"{row['Pisen']} od {row['Umelec']}", value=selected, key=f"checkbox_{index}")
    if selected and index not in st.session_state.selected_indices["Zpevaci"]:
        st.session_state.selected_indices["Zpevaci"].append(index)
    elif not selected and index in st.session_state.selected_indices["Zpevaci"]:
        st.session_state.selected_indices["Zpevaci"].remove(index)

# Calculate total selected songs for all categories
total_selected = sum(len(indices) for indices in st.session_state.selected_indices.values())

# Label for the progress bar
progress_label = f"Celkem vybráno {total_selected} z 25 písní"

# Progress bar with a target of 25 total songs
progress = min(total_selected / 25, 1.0)
st.progress(progress)
st.text(progress_label)