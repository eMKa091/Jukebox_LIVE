import streamlit as st
from admin import admin_page
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

if st.query_params:
    if st.query_params["admin"] == "True":
        admin_page()
else:
    voting_page()