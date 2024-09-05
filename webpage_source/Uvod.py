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
        st.experimental_set_query_params()  # Remove query params
        st.success("Logged out of admin view. Refresh to return to the normal view.")

# Function to show the voting page
def voting_page():
    st.title("Hlasování")
    st.write("Here, you can vote for your favorite songs.")
    # Replace this with the actual voting logic from your Hlasování.py page

# Function to show the main page for regular users
def main_page():
    ###################################################
    # Show welcome back page if user is known already #
    ###################################################
    if 'uniqueID' in st.session_state:
        st.success(f"Vítej zpět, {st.session_state.uniqueID}!")
        st.write("Tvou přezdívku už známe - hlasovat můžeš pouze jednou.")
        st.session_state.show_voting_page = True  # Trigger to show voting page

    ###############################################
    # Show initial screen if the session is fresh #
    ###############################################
    else:
        st.header('Dobrý den, vážený hoste!')
        st.subheader("Vítej v aplikaci Jukebox Heroes!")
        st.write("Dnes máš jedinečnou možnost podílet se na tvorbě playlistu.")
        st.write("Ty písně, které budou mít nejvíce hlasů, zařadíme do playlistu.")
        st.divider()

        st.write('Zadej prosím svou přezdívku')
        uniqueID = st.text_input(label="Jmeno ci prezdivka", label_visibility='hidden')

        if uniqueID:
            # Save the user's nickname and a random number into session state
            st.session_state.uniqueID = uniqueID
            st.session_state.randomNumber = randint(1, 100)
            st.session_state.show_voting_page = True  # Trigger to show voting page
            st.success("Uloženo! Přesuneme vás na hlasování...")

# Check if the URL has the admin query parameter
params = st.experimental_get_query_params()

if params.get("admin") == ["True"]:
    admin_page()
else:
    # Navigate based on the session state
    if st.session_state.get("show_voting_page", False):
        voting_page()  # Display voting page (Hlasování)
    else:
        main_page()  # Display the main welcome page