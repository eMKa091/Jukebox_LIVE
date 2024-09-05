# admin_page.py
import streamlit as st

# Function to show the admin page
def admin_page():
    st.title("Admin Wall")
    st.write("This is a restricted page for admin use only.")
    
    # Admin-only functionality here
    st.write("Display secret voting results or manage the app here.")

    # Example: Display dummy results (replace with real data)
    st.write("**Voting Results:**")
    st.write("1. Song A - 45 votes")
    st.write("2. Song B - 30 votes")
    st.write("3. Song C - 25 votes")
    
    # Option to log out (removes admin query parameter)
    if st.button("Log Out"):
        st.experimental_set_query_params()  # This removes all query parameters
        st.success("Logged out of admin view. Refresh to go back to normal view.")

# Check if the URL has the admin query parameter
params = st.experimental_get_query_params()
if params.get("admin") == ["True"]:
    # Show the admin page if the query parameter is set
    admin_page()
else:
    # Show a message for non-admin users
    st.write("You are not authorized to view this page.")
