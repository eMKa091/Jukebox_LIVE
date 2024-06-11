import streamlit as st
import pandas as pd
from streamlit.report_thread import get_report_ctx

st.set_page_config(page_title='Duety')

def get_session_id():
    return get_report_ctx().session_id

def get_session_state():
    session_id = get_session_id()
    session_state = st.session_state.get(session_id=session_id, selected_songs=[], total_selected=0)
    return session_state

csvDuetyPath = "./dataSources/duety.csv"

@st.cache_data
def load_duets_data(path):
    df = pd.read_csv(path)
    return df

session_state = get_session_state()

duetsDF = load_duets_data(csvDuetyPath)
for index, row in duetsDF.iterrows():
    selected = st.checkbox(f"{row['Song']} by {row['Artists']}")
    if selected:
        if row['Song'] not in session_state.selected_songs:
            session_state.selected_songs.append(row['Song'])
            session_state.total_selected += 1

st.write(f"Total selected songs: {session_state.total_selected}")