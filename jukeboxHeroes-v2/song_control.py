import streamlit as st
import pandas as pd
import sqlite3
from database import (add_song, get_event_name, assign_song_to_event, remove_song_from_event, get_songs_for_event)
DATABASE = 'votes.db'

def upload_songs_csv():
    st.divider()
    st.subheader("Upload new song list (CSV)")

    # CSV Upload
    uploaded_file = st.file_uploader("Choose a CSV file", type="csv")

    # Initialize session state for storing the uploaded data
    if 'uploaded_songs' not in st.session_state:
        st.session_state['uploaded_songs'] = []  # Empty list initially

    if uploaded_file is not None:
        try:
            df = pd.read_csv(uploaded_file)
            if 'Author' in df.columns and 'Song' in df.columns:
                added_count = 0
                skipped_count = 0
                uploaded_songs = []

                for _, row in df.iterrows():
                    title = row['Song']
                    artist = row['Author']

                    # Try to add the song, if it's not a duplicate
                    if add_song(title, artist):
                        added_count += 1
                        uploaded_songs.append((title, artist))  # Store added songs
                    else:
                        skipped_count += 1

                st.session_state['uploaded_songs'] = uploaded_songs  # Save uploaded songs to session

                st.success(f"Uploaded {added_count} songs successfully, please save to DB.")

                if skipped_count > 0:
                    st.info(f"Skipped {skipped_count} duplicates.")
            else:
                st.error("CSV must have 'Author' and 'Song' columns.")
        except Exception as e:
            st.error(f"Error processing the file: {e}")

def song_management(event_id, round_id):
    event_name = get_event_name(event_id)
    
    # Fetch number of rounds for the event
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT round_count FROM events WHERE id = ?", (event_id,))
    round_count = c.fetchone()[0]
    conn.close()

    # Use session state to track the current round
    if 'round_id' not in st.session_state:
        st.session_state['round_id'] = round_id  # Initialize with the provided round_id

    current_round_id = st.session_state['round_id']

    st.divider()

    # Case 1: Single-round event
    if round_count == 1:
        st.info("All songs from master DB were assigned by default, hence you can only remove songs below!")
        st.divider()

        conn = sqlite3.connect(DATABASE)
        # Fetch all songs assigned to this event (no round_id filtering since it's a single-round event)
        df_event_songs = pd.read_sql_query(
            """
            SELECT s.id, s.title, s.artist 
            FROM songs s 
            JOIN event_songs es ON s.id = es.song_id 
            WHERE es.event_id = ? AND es.played = 0
            """, 
            conn, params=(event_id,)
        )
        conn.close()

        if not df_event_songs.empty:
            selected_songs_to_remove = st.multiselect(
                ":x: Remove from event:", 
                options=df_event_songs['id'].tolist(), 
                format_func=lambda x: f"{df_event_songs[df_event_songs['id'] == x]['title'].values[0]} by {df_event_songs[df_event_songs['id'] == x]['artist'].values[0]}",
                key="remove_songs_multiselect"
            )

            if st.button("Remove selected songs"):
                for song_id in selected_songs_to_remove:
                    remove_song_from_event(event_id, song_id)
                st.success(f"Removed selected songs from event '{event_name}'.")

            if st.button("Remove All Songs from Event"):
                remove_all_songs_from_event(event_id)
                st.success(f"All songs removed from event '{event_name}'.")

    # Case 2: Multi-round event
    else:
        st.subheader(f":male-mechanic: Manage songs for round {current_round_id}", divider=True)

        # Fetch songs assigned to this specific round
        conn = sqlite3.connect(DATABASE)
        df_event_songs = pd.read_sql_query(
            """
            SELECT s.id, s.title, s.artist 
            FROM songs s 
            JOIN event_songs es ON s.id = es.song_id 
            WHERE es.event_id = ? AND es.round_id = ? AND es.played = 0
            """,
            conn, params=(event_id, current_round_id)
        )
        conn.close()

        col1, col2 = st.columns(2)

        ###############################
        # Remove songs that the band will play anyway #
        ###############################
        with col1:
            st.write("")                   
            if not df_event_songs.empty:
                selected_songs_to_remove = st.multiselect(
                    ":x: Remove from round:", 
                    options=df_event_songs['id'].tolist(), 
                    format_func=lambda x: f"{df_event_songs[df_event_songs['id'] == x]['title'].values[0]} by {df_event_songs[df_event_songs['id'] == x]['artist'].values[0]}",
                    key="remove_songs_multiselect"
                )

                if st.button("Remove selected songs from round"):
                    for song_id in selected_songs_to_remove:
                        remove_song_from_event(event_id, song_id)
                    st.success(f"Removed selected songs from round {current_round_id}.")
                    st.rerun()
            else:
                st.write(f"No songs are assigned to round {current_round_id}.")

        ########################################
        #  Mark played songs in current round  #
        ########################################
        with col2:
            st.write("")
            selected_songs_as_played = st.multiselect(
                ":white_check_mark: Mark as played:", 
                options=df_event_songs['id'].tolist(), 
                format_func=lambda x: f"{df_event_songs[df_event_songs['id'] == x]['title'].values[0]} by {df_event_songs[df_event_songs['id'] == x]['artist'].values[0]}",
                key="mark_songs_as_played_multiselect"
            )

            if st.button("Mark selected songs as played"):
                for song_id in selected_songs_as_played:
                    mark_song_as_played(event_id, song_id)
                st.success(f"Marked {len(selected_songs_as_played)} song(s) as played for round {current_round_id}.")
                st.rerun()

        ###########################
        #  Prepare another round  #
        ###########################
        st.write("")
        st.subheader(":female-mechanic: Another round settings", divider=True)
        st.warning("Press below button only if you marked already played songs")

        if st.button("Assign remaining songs to another round"):
            assign_remaining_songs_to_next_round(event_id, current_round_id)

            # Move to the next round if available
            if current_round_id < round_count:
                st.session_state['round_id'] = current_round_id + 1  # Shift to the next round
                st.rerun()
            else:
                st.success(f"All rounds for event '{event_name}' have been managed.")

        ######################################
        #  Show overview of songs per round  #
        ######################################
        st.write("")
        show_songs_per_round(event_id)

def check_songs_exist():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM songs")
    count = c.fetchone()[0]
    conn.close()
    return count > 0

def export_votes_to_csv():
    conn = sqlite3.connect(DATABASE)
    df_votes = pd.read_sql_query("SELECT * FROM votes", conn)
    conn.close()
    
    # Convert DataFrame to CSV and provide download link
    csv = df_votes.to_csv(index=False)
    st.download_button("Download Votes CSV", data=csv, file_name="votes_backup.csv", mime="text/csv")

def export_songs_to_csv():
    conn = sqlite3.connect(DATABASE)
    
    # Fetch songs only from the songs table to avoid duplications
    df_songs = pd.read_sql_query("SELECT DISTINCT * FROM songs", conn)
    conn.close()
    
    # Convert DataFrame to CSV and provide download link
    csv = df_songs.to_csv(index=False)
    st.download_button("Download Songs CSV", data=csv, file_name="songs_backup.csv", mime="text/csv")

def fetch_songs_for_voting(event_id, round_id=None):
    """
    Fetches all songs assigned to a given event and round for the voting page.
    If round_id is None, it fetches songs for single-round events.
    """
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    if round_id:
        # Fetch songs for the specific round in a multi-round event
        c.execute('''
            SELECT DISTINCT songs.id, songs.title, songs.artist
            FROM event_songs
            JOIN songs ON event_songs.song_id = songs.id
            WHERE event_songs.event_id = ? AND event_songs.round_id = ? AND event_songs.played = 0
        ''', (event_id, round_id))
    else:
        # Fetch all songs for a single-round event (no round_id filtering)
        c.execute('''
            SELECT DISTINCT songs.id, songs.title, songs.artist
            FROM songs
            JOIN event_songs ON songs.id = event_songs.song_id
            WHERE event_songs.event_id = ? AND event_songs.played = 0
        ''', (event_id,))

    songs = c.fetchall()
    conn.close()
    return songs

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

def mark_song_as_played(event_id, song_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    
    # Mark the song as played for the given event
    c.execute('''
        UPDATE event_songs
        SET played = 1
        WHERE event_id = ? AND song_id = ?
    ''', (event_id, song_id))
    
    conn.commit()
    conn.close()

def show_songs_per_round(event_id):

    """Display songs assigned to each round of the event."""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # Fetch the number of rounds for the event
    c.execute("SELECT round_count FROM events WHERE id = ?", (event_id,))
    round_count = c.fetchone()[0]

    st.subheader(f":loop: Songs assigned to each round", divider=True)

    # Loop through each round and display songs assigned to that round
    for round_id in range(1, round_count + 1):
        with st.expander(f"Round {round_id}", expanded=False):
            # Fetch songs assigned to this specific round
            c.execute('''
                SELECT s.title, s.artist
                FROM songs s
                JOIN event_songs es ON s.id = es.song_id
                WHERE es.event_id = ? AND es.round_id = ? AND es.played = 0
            ''', (event_id, round_id))
            songs = c.fetchall()

            if songs:
                for title, artist in songs:
                    st.write(f"- {title} by {artist}")
            else:
                st.write("No songs assigned to this round.")

    conn.close()

def assign_remaining_songs_to_next_round(event_id, current_round_id):
    """
    Assign remaining songs (event songs - played) to the next round.
    """
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # 1. Fetch all songs assigned to the event (excluding played songs)
    c.execute('''
        SELECT song_id 
        FROM event_songs
        WHERE event_id = ? AND played = 0 AND round_id <= ?
    ''', (event_id, current_round_id))
    remaining_songs = [song[0] for song in c.fetchall()]  # Song IDs of all songs that are not played

    if remaining_songs:
        next_round_id = current_round_id + 1

        # 2. Assign remaining songs to the next round
        for song_id in remaining_songs:
            # Check if the song is already assigned to the next round
            c.execute('''
                SELECT COUNT(*) FROM event_songs WHERE event_id = ? AND song_id = ? AND round_id = ?
            ''', (event_id, song_id, next_round_id))
            if c.fetchone()[0] == 0:  # Only insert if not already assigned
                c.execute('''
                    INSERT INTO event_songs (event_id, song_id, round_id)
                    VALUES (?, ?, ?)
                ''', (event_id, song_id, next_round_id))

        conn.commit()
        st.success(f"{len(remaining_songs)} remaining song(s) assigned to Round {next_round_id}.")
    else:
        st.warning("No remaining songs to assign.")

    conn.close()