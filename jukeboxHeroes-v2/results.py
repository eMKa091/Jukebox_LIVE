import streamlit as st
import sqlite3
import pandas as pd

# Database file path
DATABASE = 'votes.db'

def get_event_data():
    conn = sqlite3.connect(DATABASE)
    
    # Retrieve events
    events_query = '''
    SELECT id, name, date, round_count, current_round, voting_round 
    FROM events
    '''
    events = pd.read_sql_query(events_query, conn)
    
    # Retrieve votes with song details (title and artist)
    votes_query = '''
    SELECT
        v.event_id,
        v.round_id,
        s.title AS song_title,
        s.artist AS song_artist,
        COUNT(v.id) as vote_count
    FROM votes v
    JOIN songs s ON v.song = s.id  -- Assuming 'song' in votes table is the song ID that matches 'id' in songs table
    GROUP BY v.event_id, v.round_id, v.song
    ORDER BY v.event_id, v.round_id, vote_count DESC
    '''
    votes = pd.read_sql_query(votes_query, conn)
    
    conn.close()
    return events, votes

def display_event_results(events, votes):
    for _, event in events.iterrows():
        event_id = event['id']
        event_name = event['name']
        
        # Filter votes data for this event
        event_votes = votes[votes['event_id'] == event_id]
        
        if event_votes.empty:
            st.write(f"No votes found for {event_name}.")
            continue
        
        # Group by round_id within the event
        rounds = event_votes.groupby('round_id')

        with st.expander(f"{event_name} - {event['date']}"):
            for round_id, round_data in rounds:
                st.subheader(f"Round ID {round_id}")

                # Sort songs by vote count within each round
                sorted_songs = round_data.sort_values(by='vote_count', ascending=False)

                # Create a ranking column without using pandas indexing
                rankings = list(range(1, len(sorted_songs) + 1))
                sorted_songs.insert(0, 'Rank', rankings)  # Insert as first column

                # Select and rename columns for display
                display_data = sorted_songs[['Rank', 'song_title', 'song_artist', 'vote_count']]
                display_data.columns = ['Rank', 'Title', 'Artist', 'Votes']

                # Display table with ranking
                st.table(display_data)
