import streamlit as st
import pandas as pd
from streamlit.report_thread import get_report_ctx # type: ignore

st.set_page_config(page_title='Domovská stránka')

def get_session_id():
    return get_report_ctx().session_id

def get_session_state():
    session_id = get_session_id()
    session_state = st.session_state.get(session_id=session_id, selected_songs=[], total_selected=0)
    return session_state

st.header('Hello dear listener!')
st.write('Please select up to 25 songs you want us to play from these categories:')

col1, col2 = st.columns(2, gap="small")

with col1:
    if st.button("Duety"):
        st.switch_page("pages/Duety.py")
with col1:
    if st.button("Rock and Roll"):
        st.switch_page("pages/Rock and Roll.py")
with col1:
    if st.button("Zpěvačky"):
        st.switch_page("pages/Zpěvačky.py")
with col2:
    if st.button("Zpěváci"):
        st.switch_page("pages/Zpěváci.py")
with col2:
    if st.button("České písně"):
        st.switch_page("pages/České písně.py")

st.write('or see the full list of songs:')
