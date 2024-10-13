import streamlit as st
import sqlite3
import hashlib
import pandas as pd
from database import (
    fetch_admin_user, add_song, get_songs_for_event, update_song, assign_song_to_event,
    create_event, fetch_votes
)

# Hashing function for security
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Function to authenticate admin user
def authenticate(username, password):
    user = fetch_admin_user(username)
    if user and user[2] == hash_password(password):  # user[2] is the password_hash
        return True
    else: 
        return False

# Streamlit login form
def admin_login():
    st.title("Admin Login")

    # Login form
    with st.form(key='login_form'):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        login_button = st.form_submit_button("Login")

    # Handle login
    if login_button:
        if authenticate(username, password):
            st.success("Login successful!")
            st.session_state['logged_in'] = True
        else:
            st.error("Invalid username or password")

#####################################
# EVENT MANAGEMENT FUNCTIONS #
#####################################
def event_management():
    st.subheader("Create event")

    # Create a new event
    with st.form(key='create_event_form'):
        new_event_name = st.text_input("Event Name")
        new_event_date = st.date_input("Event Date")
        new_event_rounds = st.number_input("Number of Rounds", min_value=1, max_value=10, value=1)
        create_event_button = st.form_submit_button("Create Event")

        # Handle event creation
        if create_event_button and new_event_name and new_event_date:
            event_id = create_event(new_event_name, str(new_event_date), new_event_rounds)
            st.success(f"Event '{new_event_name}' created with ID {event_id}")

    # Fetch and display events dynamically
    conn = sqlite3.connect('votes.db')
    c = conn.cursor()
    c.execute('SELECT id, name FROM events')
    events = c.fetchall()
    conn.close()

    # If there are no events, show a message to create one
    if not events:
        st.warning("No events found. Please create an event before proceeding.")
        return None

    # Dropdown to select event for managing songs
    event_id = st.selectbox("Select Event for Song Management", options=[(event[0], event[1]) for event in events], format_func=lambda x: x[1])
    
    # Return selected event ID
    return event_id[0]  # Returning the event_id to use in song management

############################
# SONG MANAGEMENT FUNCTION #
############################
def song_management(event_id):
    st.subheader("Song Management")

    # Display current song list for the event
    current_songs = get_songs_for_event(event_id)
    
    st.write("Current Songs for this Event:")
    for song in current_songs:
        with st.expander(f"{song[1]} - {song[2]}"):
            new_title = st.text_input(f"Edit title for '{song[1]}'", value=song[1])
            new_artist = st.text_input(f"Edit artist for '{song[2]}'", value=song[2])
            if st.button(f"Update Song {song[1]}"):
                update_song(song[0], new_title, new_artist)  # song[0] is the song ID
                st.success(f"Song '{new_title}' updated successfully!")

    # Add new songs
    st.subheader("Add a New Song")
    new_song_title = st.text_input("Song Title")
    new_song_artist = st.text_input("Artist")
    if st.button("Add Song"):
        song_id = add_song(new_song_title, new_song_artist)
        assign_song_to_event(event_id, song_id)  # Assign this song to the current event
        st.success(f"Added '{new_song_title}' to event setlist")


#############################
# DATABASE BACKUP FUNCTIONS #
#############################
# Export votes to CSV
def export_votes_to_csv():
    conn = sqlite3.connect('votes.db')
    df_votes = pd.read_sql_query("SELECT * FROM votes", conn)
    conn.close()
    
    # Convert DataFrame to CSV and provide download link
    csv = df_votes.to_csv(index=False)
    st.download_button("Download Votes CSV", data=csv, file_name="votes_backup.csv", mime="text/csv")

# Export songs to CSV
def export_songs_to_csv():
    conn = sqlite3.connect('votes.db')
    df_songs = pd.read_sql_query("SELECT * FROM songs", conn)
    conn.close()
    
    # Convert DataFrame to CSV and provide download link
    csv = df_songs.to_csv(index=False)
    st.download_button("Download Songs CSV", data=csv, file_name="songs_backup.csv", mime="text/csv")


##########
# Backup #
##########
def backup_data_section():
    st.subheader("Data Backup")
    export_votes_to_csv()
    export_songs_to_csv()


###########################################
# MAIN ADMIN DASHBOARD AND NAVIGATION #
###########################################
if 'logged_in' in st.session_state and st.session_state['logged_in']:
    st.title("Admin Dashboard")

    #################
    # CREATE EVENTS #
    #################
    event_id = event_management()

    ###################
    # SONG MANAGEMENT #
    ###################
    song_management(event_id)

    ##########
    # BACKUP #
    ##########
    backup_data_section()

    # The rest of the admin functionalities (Voting Control) will go here
else:
    admin_login()