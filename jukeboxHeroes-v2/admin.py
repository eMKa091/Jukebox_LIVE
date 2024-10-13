import streamlit as st
import sqlite3
import hashlib
import pandas as pd
from database import (
    fetch_admin_user, add_song, get_songs_for_event, assign_song_to_event,
    remove_song_from_event, create_event, delete_event, get_event_name
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

##############################
# EVENT MANAGEMENT FUNCTIONS #
##############################
def event_management():
    st.subheader("Create new event")

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

    # Show events in a table with delete buttons
    for event in events:
        if st.button(f"Delete Event {event[1]}", key=f"delete_{event[0]}"):
            delete_event(event[0])
            st.success(f"Event '{event[1]}' and all related data have been deleted.")
            st.rerun()  # Refresh the page to update event list

    st.divider()
    # Dropdown to select event for managing songs
    event_id = st.selectbox("Select Event for Song Management", options=[(event[0], event[1]) for event in events], format_func=lambda x: x[1])
    
    # Return selected event ID
    return event_id[0]  # Returning the event_id to use in song management

#############################
# SONG MANAGEMENT FUNCTIONS #
#############################
def upload_songs_csv():
    st.divider()
    st.subheader("Upload new song list (CSV)")

    # CSV Upload
    uploaded_file = st.file_uploader("Choose a CSV file", type="csv")
    if uploaded_file is not None:
        try:
            df = pd.read_csv(uploaded_file)
            if 'Author' in df.columns and 'Song' in df.columns:
                for _, row in df.iterrows():
                    add_song(row['Song'], row['Author'])  # 'Song' is title, 'Author' is artist
                st.success(f"Uploaded {len(df)} songs successfully.")
            else:
                st.error("CSV must have 'Author' and 'Song' columns.")
        except Exception as e:
            st.error(f"Error processing the file: {e}")

def song_management(event_id):
    event_name = get_event_name(event_id)
    st.divider()
    st.subheader(f"Song management for venue: {event_name}")

    # Split layout for master song list and event-specific songs
    col1, col2 = st.columns(2)

    #############################
    # Master Song List (Adding) #
    #############################
    with col1:
        conn = sqlite3.connect('votes.db')
        df_master = pd.read_sql_query("SELECT * FROM songs", conn)
        conn.close()

        # Display the master song list and allow adding songs to the event
        if not df_master.empty:
            st.write("Select songs to add:")
            selected_songs = st.multiselect(
                "Add to event:", 
                options=df_master['id'].tolist(), 
                format_func=lambda x: f"{df_master[df_master['id'] == x]['title'].values[0]} by {df_master[df_master['id'] == x]['artist'].values[0]}",
                key="add_songs_multiselect"  # Unique key for adding songs
            )
            if st.button("Add Songs to Event"):
                for song_id in selected_songs:
                    assign_song_to_event(event_id, song_id)
                st.success(f"Added {len(selected_songs)} songs to the event.")
        else:
            st.info("No songs available. Please upload a song list.")

    #############################
    # Event Song List (Removing) #
    #############################
    with col2:
        current_songs = get_songs_for_event(event_id)

        if current_songs:
            # Display the current songs in a table with checkboxes
            df_event = pd.DataFrame(current_songs, columns=['id', 'title', 'artist'])

            # Display the table with checkboxes
            st.write("Select songs to remove:")
            selected_to_remove = st.multiselect(
                "Remove from event:", 
                options=df_event['id'].tolist(), 
                format_func=lambda x: f"{df_event[df_event['id'] == x]['title'].values[0]} by {df_event[df_event['id'] == x]['artist'].values[0]}",
                key="remove_songs_multiselect"  # Unique key for removing songs
            )

            # Remove the selected songs when the button is clicked
            if st.button("Remove Selected Songs"):
                for song_id in selected_to_remove:
                    remove_song_from_event(event_id, song_id)
                st.success(f"Removed {len(selected_to_remove)} songs from the event.")
        else:
            st.info(f"No songs assigned to {event_name} yet.")

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
    
    # Fetch songs only from the songs table to avoid duplications
    df_songs = pd.read_sql_query("SELECT DISTINCT * FROM songs", conn)
    conn.close()
    
    # Convert DataFrame to CSV and provide download link
    csv = df_songs.to_csv(index=False)
    st.download_button("Download Songs CSV", data=csv, file_name="songs_backup.csv", mime="text/csv")

##########
# Backup #
##########
def backup_data_section():
    st.divider()
    st.subheader("Data backup")
    export_votes_to_csv()
    export_songs_to_csv()

###########################################
# MAIN ADMIN DASHBOARD AND NAVIGATION #
###########################################
if 'logged_in' in st.session_state and st.session_state['logged_in']:
    st.title("Admin Dashboard")
    st.divider()
    #################
    # CREATE EVENTS #
    #################
    event_id = event_management()

    # If event_id is None, skip song management
    if event_id:
        ###################
        # SONG MANAGEMENT #
        ###################
        song_management(event_id)  # Manage songs for the selected event
        upload_songs_csv()  # Upload new songs

    ##########
    # BACKUP #
    ##########
    backup_data_section()

else:
    admin_login()