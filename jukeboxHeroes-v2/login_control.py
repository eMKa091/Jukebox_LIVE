import streamlit as st
import hashlib
from database import fetch_admin_user

# Hashing function for security
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Authenticate user with hashed password
def authenticate(username, password):
    user = fetch_admin_user(username)
    return user and user[2] == hash_password(password)

# Define the callback function for setting logged_in
def handle_login(username, password):
    if authenticate(username, password):
        st.session_state['logged_in'] = True
        st.session_state['page'] = 'admin'
        st.rerun()
    else:
        st.error("Invalid username or password")

# Admin login page with form
def admin_login():
    st.title("Admin login")

    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    # Use a button to handle the login, triggering the login function
    if st.button("Login"):
        handle_login(username, password)