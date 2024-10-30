import streamlit as st
from admin import admin_page
from voting import voting_page
from band import band_page
from database import add_admin_user

# Uncomment to add an admin user for testing purposes
add_admin_user("", "")

if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'page' not in st.session_state:
    st.session_state['page'] = 'voting'

if st.query_params:
    if st.query_params["admin"] == "Boss":
        admin_page()
    elif st.query_params["admin"] == "Band":
        band_page()
else:
    voting_page()