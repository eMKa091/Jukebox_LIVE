import streamlit as st
from random import randint

st.header('Dobrý den, vážení hosté!')
st.write('Zadejte prosím vaši přezdívku')
uniqueID = st.text_input(label="Jmeno ci prezdivka", label_visibility='hidden')

if uniqueID:
    st.session_state.uniqueID = uniqueID
    st.success("Uloženo! Přesuneme vás na další stránku...")
    randomNumber = randint(1, 100)
    st.session_state.randomNumber = randomNumber
    st.switch_page("pages/1_České písně.py")