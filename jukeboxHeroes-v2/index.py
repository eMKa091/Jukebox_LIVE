import streamlit as st
from admin import admin_page
from voting import voting_page
from band import band_page
from database import add_admin_user

# Uncomment this if you want to add an admin user
add_admin_user("a", "a")

# Get the query parameters using the new API
params = st.query_params  # st.query_params returns a dictionary-like object

# Check if 'admin' query parameter exists and render the correct page
if 'admin' in params and params['admin'] == 'True':  # Compare directly to string 'True'
    admin_page()

elif 'band' in params and params['band'] == 'True':
    band_page()

else:
    voting_page()