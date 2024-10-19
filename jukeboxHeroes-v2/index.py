import streamlit as st
from admin import admin_page
from voting import voting_page
from database import add_admin_user

# Uncomment this if you want to add an admin user
# add_admin_user("a", "a")

if 'page' not in st.session_state:
    st.session_state['page'] = 'admin'  # Default to admin page

# Page selection logic
if st.session_state['page'] == 'admin':
    admin_page()  # Call the admin_page function from admin.py

elif st.session_state['page'] == 'voting':
    voting_page()  # Call the voting_page function from voting.py