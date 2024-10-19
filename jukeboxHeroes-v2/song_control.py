import streamlit as st
import pandas as pd
import sqlite3
from database import (add_song, get_event_name, assign_song_to_event, remove_song_from_event, get_songs_for_event)
DATABASE = 'votes.db'

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

def song_management(event_id, round_id):
    event_name = get_event_name(event_id)
    st.divider()
    st.subheader(f"Songs (Event: {event_name}, Round: {round_id})")

    # Split layout for master song list and event-specific songs
    col1, col2 = st.columns(2)

    #############################
    # Master Song List (Adding) #
    #############################
    with col1:
        conn = sqlite3.connect(DATABASE)
        df_event_songs = pd.read_sql_query(
            "SELECT songs.id, songs.title, songs.artist FROM event_songs JOIN songs ON event_songs.song_id = songs.id WHERE event_songs.event_id = ? AND (event_songs.round_id = ? OR event_songs.round_id IS NULL)", 
            conn, 
            params=(event_id, round_id)
            )
        conn.close()

        # Display the master song list and allow adding songs to the event
        if not df_event_songs.empty:
            st.write("Select songs to add:")
            selected_songs_to_add = st.multiselect(
                "Add to event:", 
                options=df_event_songs['id'].tolist(), 
                format_func=lambda x: f"{df_event_songs[df_event_songs['id'] == x]['title'].values[0]} by {df_event_songs[df_event_songs['id'] == x]['artist'].values[0]}",
                key="add_songs_multiselect"
            )

            # Add Songs Button
            if st.button("Add Selected Songs"):
                added_songs = []
                already_assigned_songs = []

                if selected_songs_to_add:
                    for song_id in selected_songs_to_add:
                        if assign_song_to_event(event_id, song_id, round_id):
                            added_songs.append(song_id)
                        else:
                            already_assigned_songs.append(song_id)

                    # Display summary message
                    st.write(f"{len(added_songs)} song(s) were added to event '{event_name}' (Round: {round_id}).")
                    st.write(f"{len(already_assigned_songs)} song(s) were already assigned.")

        if st.button("Add All Songs to Event"):
            add_all_songs_to_event(event_id, round_id)
            st.success(f"All songs were added to event '{event_name}' (Round: {round_id if round_id else 'No Round'}).")

    #######################################
    # Event-Specific Song List (Removing) #
    #######################################
    with col2:
        conn = sqlite3.connect(DATABASE)
        df_event_songs = pd.read_sql_query(
            "SELECT songs.id, songs.title, songs.artist FROM event_songs JOIN songs ON event_songs.song_id = songs.id WHERE event_songs.event_id = ? AND event_songs.round_id = ?", 
            conn, 
            params=(event_id, round_id)
        )
        conn.close()

        if not df_event_songs.empty:
            st.write("Select songs to remove:")
            selected_songs_to_remove = st.multiselect(
                "Remove from event:", 
                options=df_event_songs['id'].tolist(), 
                format_func=lambda x: f"{df_event_songs[df_event_songs['id'] == x]['title'].values[0]} by {df_event_songs[df_event_songs['id'] == x]['artist'].values[0]}",
                key="remove_songs_multiselect"
            )
            if st.button("Remove All Songs from Event"):
                remove_all_songs_from_event(event_id)
                st.success(f"All songs were removed from event {event_name}.")
            
            # Remove Songs Button
            if st.button("Remove Selected Songs"):
                removed_songs = []

                if selected_songs_to_remove:
                    for song_id in selected_songs_to_remove:
                        remove_song_from_event(event_id, song_id, round_id)
                        removed_songs.append(song_id)

                    # Display summary message
                    st.write(f"{len(removed_songs)} song(s) were removed from event '{event_name}' (Round: {round_id}).")

def check_songs_exist():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM songs")
    count = c.fetchone()[0]
    conn.close()
    return count > 0

#############################
# DATABASE BACKUP FUNCTIONS #
#############################
# Export votes to CSV
def export_votes_to_csv():
    conn = sqlite3.connect(DATABASE)
    df_votes = pd.read_sql_query("SELECT * FROM votes", conn)
    conn.close()
    
    # Convert DataFrame to CSV and provide download link
    csv = df_votes.to_csv(index=False)
    st.download_button("Download Votes CSV", data=csv, file_name="votes_backup.csv", mime="text/csv")

# Export songs to CSV
def export_songs_to_csv():
    conn = sqlite3.connect(DATABASE)
    
    # Fetch songs only from the songs table to avoid duplications
    df_songs = pd.read_sql_query("SELECT DISTINCT * FROM songs", conn)
    conn.close()
    
    # Convert DataFrame to CSV and provide download link
    csv = df_songs.to_csv(index=False)
    st.download_button("Download Songs CSV", data=csv, file_name="songs_backup.csv", mime="text/csv")

# Function to fetch songs for voting
def fetch_songs_for_voting(event_id, round_id=None):
    """
    Fetches all distinct songs assigned to a given event and round for the voting page.
    """
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    if round_id:
        c.execute('''
            SELECT DISTINCT songs.id, songs.title, songs.artist 
            FROM songs
            JOIN event_songs ON songs.id = event_songs.song_id
            WHERE event_songs.event_id = ? AND event_songs.round_id = ?
        ''', (event_id, round_id))
    else:
        c.execute('''
            SELECT DISTINCT songs.id, songs.title, songs.artist 
            FROM songs
            JOIN event_songs ON songs.id = event_songs.song_id
            WHERE event_songs.event_id = ?
        ''', (event_id,))

    songs = c.fetchall()
    conn.close()
    return songs  # Return only assigned songs

def display_song_selection(songs, max_selection=5):
    """
    Displays song selection checkboxes with a maximum selection limit of 5 songs.
    """
    if 'selected_songs' not in st.session_state:
        st.session_state['selected_songs'] = []

    selected_songs = st.session_state['selected_songs']
    num_selected = len(selected_songs)

    # Display the current number of selected songs
    st.subheader(f"Select up to {max_selection} songs:")
    st.markdown(f"**{num_selected} / {max_selection} selected**")

    # Display checkboxes for song selection
    cols = st.columns(2)  # Responsive layout for mobile
    for i, (song_id, song_title, song_artist) in enumerate(songs):
        checked = song_id in selected_songs
        disabled = (not checked and num_selected >= max_selection)  # Disable extra selections

        with cols[i % 2]:  # Distribute songs across 2 columns
            if st.checkbox(f"{song_title} by {song_artist}", key=f"song_{song_id}", value=checked, disabled=disabled):
                if not checked:
                    selected_songs.append(song_id)
            else:
                if checked:
                    selected_songs.remove(song_id)

        # Update session state
        st.session_state['selected_songs'] = selected_songs
        num_selected = len(selected_songs)

    # Once 5 songs are selected, move to the confirmation stage
    if num_selected == max_selection:
        st.session_state['confirming_selection'] = True  # Set the confirmation state

def get_song_name(song_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('SELECT title FROM songs WHERE id = ?', (song_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 'Unknown Song'

def remove_all_songs_from_event(event_id, round_id=None):
    """
    Removes all songs from a specific event and round (or all rounds if round_id is None).
    """
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        if round_id:
            c.execute('''
                DELETE FROM event_songs 
                WHERE event_id = ? AND round_id = ?
            ''', (event_id, round_id))
        else:
            c.execute('''
                DELETE FROM event_songs 
                WHERE event_id = ?
            ''', (event_id,))
        conn.commit()

def add_all_songs_to_event(event_id, round_id=None):
    """
    Adds all songs from the master song list to a specific event and round.
    If round_id is None, adds the songs without assigning a round.
    """
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()

        # Get all song IDs from the songs table (master list)
        c.execute('SELECT id FROM songs')
        all_songs = c.fetchall()

        # Loop through each song and add it to the event
        for song in all_songs:
            song_id = song[0]

            # Check if the song is already assigned to avoid duplicates
            if round_id is None:
                # Handle the case where round_id is NULL
                c.execute('''
                    SELECT COUNT(*) FROM event_songs 
                    WHERE event_id = ? AND song_id = ? AND round_id IS NULL
                ''', (event_id, song_id))
            else:
                # Handle the case where round_id is provided
                c.execute('''
                    SELECT COUNT(*) FROM event_songs 
                    WHERE event_id = ? AND song_id = ? AND round_id = ?
                ''', (event_id, song_id, round_id))

            if c.fetchone()[0] == 0:  # Only add if not already assigned
                c.execute('''
                    INSERT INTO event_songs (event_id, song_id, round_id)
                    VALUES (?, ?, ?)
                ''', (event_id, song_id, round_id))

        conn.commit()
