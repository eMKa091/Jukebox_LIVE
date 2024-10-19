import streamlit as st
from login_control import authenticate

def band_login():
    st.title("Band Login")

    with st.form(key='band_login_form'):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        login_button = st.form_submit_button("Login")

    if login_button:
        if authenticate(username, password):
            st.success("Login successful!")
            st.session_state['band_logged_in'] = True
            st.rerun()
        else:
            st.error("Invalid username or password")

def band_page():
    if 'band_logged_in' not in st.session_state or not st.session_state['band_logged_in']:
        band_login()
    else:
        st.title("Band Dashboard")
        # Display band-specific data here