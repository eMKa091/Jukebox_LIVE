import streamlit as st
import pandas as pd

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
