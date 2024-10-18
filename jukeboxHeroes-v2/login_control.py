import streamlit as st
import hashlib
from database import fetch_admin_user

# Hashing function for security
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def authenticate(username, password):
    user = fetch_admin_user(username)
    if user and user[2] == hash_password(password):  
        return True
    else: 
        return False

def admin_login():
    st.title("Admin Login")

    with st.form(key='login_form'):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        login_button = st.form_submit_button("Login")

    if login_button:
        if authenticate(username, password):
            st.success("Login successful!")
            st.session_state['logged_in'] = True
            st.rerun()
        else:
            st.error("Invalid username or password")