import streamlit as st
from random import randint

st.header('Dobrý den, vážení hosté!')

# Check if the uniqueID is already in session state
if 'uniqueID' in st.session_state:
    st.success(f"Vítejte zpět, {st.session_state.uniqueID}!")
    st.write("Již jste zadali své jméno a hlasovat můžete pouze jednou.")
    
    # Add a button to navigate to the next page
    if st.button("Pokračovat na další stránku"):
        st.switch_page("pages/1_České písně.py")
else:
    st.write('Zadejte prosím vaši přezdívku')
    uniqueID = st.text_input(label="Jmeno ci prezdivka", label_visibility='hidden')

    if uniqueID:
        st.session_state.uniqueID = uniqueID
        st.success("Uloženo! Přesuneme vás na další stránku...")
        randomNumber = randint(1, 100)
        st.session_state.randomNumber = randomNumber
        st.switch_page("pages/1_České písně.py")
