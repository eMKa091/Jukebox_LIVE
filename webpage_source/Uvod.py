import streamlit as st
from random import randint

###################################################
# Show welcome back page if user is known already #
###################################################
# Check if the uniqueID is already in session state
if 'uniqueID' in st.session_state:
    st.success(f"Vítej zpět, {st.session_state.uniqueID}!")
    st.write("Tvou přezdívku už známe - hlasovat můžeš pouze jednou.")
    
    # Add buttons to navigate to the next page
    if st.button("Pokračovat na České písně"):
        st.switch_page("pages/1_České písně.py")
    if st.button("Pokračovat na Duety"):
        st.switch_page("pages/2_Duety.py")
    if st.button("Pokračovat na Rock and roll"):
        st.switch_page("pages/3_Rock and Roll.py")
    if st.button("Pokračovat na mužské interprety"):
        st.switch_page("pages/4_Zpěváci.py")
    if st.button("Pokračovat na ženské interprety"):
        st.switch_page("pages/5_Zpěvačky.py")

###############################################
# Show initial screen if the session is fresh #
###############################################
else:
    st.header('Dobrý den, vážení hosté!')
    st.write('Zadejte prosím vaši přezdívku')
    uniqueID = st.text_input(label="Jmeno ci prezdivka", label_visibility='hidden')

    if uniqueID:
        st.session_state.uniqueID = uniqueID
        st.success("Uloženo! Přesuneme vás na další stránku...")
        randomNumber = randint(1, 100)
        st.session_state.randomNumber = randomNumber
        st.switch_page("pages/1_České písně.py")
