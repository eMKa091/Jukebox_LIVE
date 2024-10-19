import streamlit as st
from admin import admin_page
from voting import voting_page
from database import add_admin_user

#add_admin_user("a", "a")

if 'page' not in st.session_state:
    st.session_state['page'] = 'admin'  # Default to admin page

if st.session_state['page'] == 'admin':
    admin_page()

if st.session_state['page'] == 'voting':
    voting_page()
