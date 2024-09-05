import streamlit as st
import pandas as pd
import sqlite3
from random import randint


# Function to show the admin page
def admin_page():
    st.title("Admin Wall")
    st.write("This is a restricted page for admin use only.")
    
    conn = sqlite3.connect('votes.db')
    c = conn.cursor()
    c.execute('SELECT uniqueID, song FROM votes')
    results = c.fetchall()
    conn.close()
    
    st.write("**Voting Results:**")
    st.write(pd.DataFrame(results, columns=["User", "Song"]).groupby("User").apply(lambda x: x['Song'].tolist()).to_dict())


# Function to show the main page for regular users
def main_page():
    # Check if the user is already in the session state
    if 'uniqueID' in st.session_state:
        st.success(f"Vítej zpět, {st.session_state.uniqueID}!")
        st.write("Tvou přezdívku už známe - hlasovat můžeš pouze jednou.")
        st.button("Pokračovat na hlasování", on_click=lambda: st.switch_page("Hlasovani"))

    # Show the welcome screen for new users
    else:
        st.header('Dobrý den, vážený hoste!')
        st.subheader("Vítej v aplikaci Jukebox Heroes!")
        st.write("Dnes máš jedinečnou možnost podílet se na tvorbě playlistu.")
        st.write("Ty písně, které budou mít nejvíce hlasů, zařadíme do playlistu.")
        
        st.divider()

        st.write('Zadej prosím svou přezdívku')
        uniqueID = st.text_input(label="Jméno či přezdívka", label_visibility='hidden')

        # Once the user provides a name, store it and redirect to voting
        if uniqueID:
            st.session_state.uniqueID = uniqueID
            st.session_state.randomNumber = randint(1, 100)
            st.success("Uloženo! Přesuneme vás na hlasování...")
            st.query_params.clear  # Clear any query params before switching pages
            st.switch_page("pages/Hlasování.py")  # Make sure the file name matches exactly

# Get the query parameters using the new API
params = st.query_params  # st.query_params returns a dictionary-like object

# Check if 'admin' query parameter exists and render the correct page
if 'admin' in params and params['admin'] == 'True':  # Compare directly to string 'True'
    admin_page()
else:
    main_page()
