import streamlit as st

st.header('Dobrý den, vážení hosté!')
st.write('Zadejte prosím vaši přezdívku')
uniqueID = st.text_input(label="Jmeno ci prezdivka", label_visibility='hidden')

if uniqueID:
    st.session_state.uniqueID = uniqueID
    st.success("Uloženo! Přesuneme vás na další stránku...")
    st.switch_page("pages/Duety.py")
