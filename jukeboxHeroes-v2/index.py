import streamlit as st
from admin import admin_page
from voting import voting_page
from database import add_admin_user

add_admin_user("admin", "JendaDva")

# Initialize the page state if it's not set
if 'page' not in st.session_state:
    st.session_state['page'] = 'admin'  # Default to admin page

# Navigation logic
if st.session_state['page'] == 'admin':
    admin_page()  # Show the admin page
elif st.session_state['page'] == 'voting':
    voting_page()  # Show the voting page