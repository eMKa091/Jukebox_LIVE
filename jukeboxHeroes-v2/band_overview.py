import streamlit as st
from login_control import authenticate

def band_login():
    st.title("Band Login")
    st.header("Authenticate please")
    
    # The form handling logic
    with st.form(key='band_login_form'):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        login_button = st.form_submit_button("Login")  # Button for form submit

    # If the login button is pressed, authenticate
    if login_button:
        if authenticate(username, password):
            st.success("Login successful!")
            st.session_state['band_logged_in'] = True  # Set session state upon successful login
            st.rerun()
        else:
            st.error("Invalid username or password")

def band_page():
    st.header("Band Section")
    
    # Handle session state for login
    if 'band_logged_in' not in st.session_state or not st.session_state['band_logged_in']:
        band_login()
    else:
        st.title("Band Dashboard")
        # Display band-specific data here (could be another function)
        st.write("Welcome to the band dashboard!")
        # Add more content for the dashboard

# Main page
if __name__ == "__main__":
    st.set_page_config(page_title="Band Section", page_icon="🎶")
    band_page()