import sqlite3
import streamlit as st

DATABASE = 'votes.db'

# Function to get current band page content from the database
def get_band_page_content():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT content FROM band_page_content ORDER BY id DESC LIMIT 1")
    result = c.fetchone()
    conn.close()
    return result[0] if result else ""

# Function to update the band page content in the database
def update_band_page_content(content):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    # Clear previous content (if any) and insert new one
    c.execute("DELETE FROM band_page_content")
    c.execute("INSERT INTO band_page_content (content) VALUES (?)", (content,))
    conn.commit()
    conn.close()

def admin_band_page_control():
    st.subheader("Please define the content for the band page")

    # Load the current content to show in the text area
    current_content = get_band_page_content()
    new_content = st.text_area("Enter playlist content for the band page:", value=current_content, height=200)

    if st.button("Save Content"):
        update_band_page_content(new_content)
        st.success("Content updated successfully!")