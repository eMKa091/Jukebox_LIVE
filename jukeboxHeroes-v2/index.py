import streamlit as st
from admin import admin_page, admin_login
from voting import voting_page
from band import band_page
from database import add_admin_user

# Uncomment to add an admin user for testing purposes
# add_admin_user("a", "a")

# Initialize session state variables if they are not already set
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'page' not in st.session_state:
    st.session_state['page'] = 'voting'  # Default to voting page if not logged in

# Navigation options based on session state
if st.session_state['logged_in']:
    # If logged in, route to the chosen page
    if st.session_state['page'] == 'admin':
        admin_page()
    elif st.session_state['page'] == 'band':
        band_page()
    else:
        voting_page()
else:
    # Show the login page if the user selects it
    if st.session_state['page'] == 'admin':
        admin_login()
    else:
        # Display voting page with option to navigate to admin login
        voting_page()
        if st.button("Admin Login"):
            st.session_state['page'] = 'admin'  # Set page to admin for login
            st.rerun()  # Trigger rerun to update page