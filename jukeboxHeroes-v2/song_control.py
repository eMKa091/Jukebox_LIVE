import streamlit as st
import pandas as pd
import sqlite3
from database import (add_song,get_event_name,assign_song_to_event,remove_song_from_event, get_songs_for_event)
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

def song_management(event_id):
    event_name = get_event_name(event_id)
    st.divider()
    st.subheader(f"Songs")

    # Split layout for master song list and event-specific songs
    col1, col2 = st.columns(2)

    #############################
    # Master Song List (Adding) #
    #############################
    with col1:
        conn = sqlite3.connect(DATABASE)
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