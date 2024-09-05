import streamlit as st
from random import randint

# Function to show the admin page
def admin_page():
    st.title("Admin Wall")
    st.write("This is a restricted page for admin use only.")
    
    # Admin-only functionality here
    st.write("Display secret voting results or manage the app here.")
    st.write("**Voting Results:**")
    st.write("1. Song A - 45 votes")
    st.write("2. Song B - 30 votes")
    st.write("3. Song C - 25 votes")

    # Option to log out (removes admin query parameter)
    if st.button("Log Out"):
        st.experimental_set_query_params()  # Clear query params
        st.success("Logged out of admin view. Refresh to return to the normal view.")

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
            st.experimental_set_query_params()  # Clear any query params before switching pages
            st.switch_page("Hlasovani")  # Make sure the file name matches exactly

# Get the query parameters using the new API
params = st.query_params  # Replaced experimental_get_query_params()

# Ensure the "admin" param is checked correctly and render the admin page
if params.get("admin") == ["True"]:
    admin_page()
else:
    main_page()
