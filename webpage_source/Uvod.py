import streamlit as st
from random import randint

###################################################
# Show welcome back page if user is known already #
###################################################
# Check if the uniqueID is already in session state
if 'uniqueID' in st.session_state:
    st.success(f"Vítej zpět, {st.session_state.uniqueID}!")
    st.write("Tvou přezdívku už známe - hlasovat můžeš pouze jednou.")
    st.write("Vítejte v aplikaci Jukebox Heroes. Dnes máte jedinečnou možnost vybrat si až 10 písní. Ty, které budou mít nejvíce bodů, zařadíme do setlistu.")
    
###############################################
# Show initial screen if the session is fresh #
###############################################
else:
    st.header('Dobrý den, vážený hoste!')
    st.write('Zadej prosím svou přezdívku')
    uniqueID = st.text_input(label="Jmeno ci prezdivka", label_visibility='hidden')

    if uniqueID:
        st.session_state.uniqueID = uniqueID
        st.success("Uloženo! Přesuneme vás na další stránku...")
        randomNumber = randint(1, 100)
        st.session_state.randomNumber = randomNumber
        st.switch_page("pages/1_České písně.py")