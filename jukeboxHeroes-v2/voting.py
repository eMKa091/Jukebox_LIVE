import streamlit as st
import sqlite3

DATABASE = 'votes.db'

# Function to get the active event for voting
def get_active_event():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('SELECT id, name, round_count, voting_active, current_round FROM events WHERE voting_active = 1')
    event = c.fetchone()
    conn.close()
    return event if event else None

# Function to fetch event details
def get_event_details(event_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('SELECT name, round_count, voting_active, current_round FROM events WHERE id = ?', (event_id,))
    event = c.fetchone()
    conn.close()
    return event if event else None

# Function to fetch songs for voting
def fetch_songs_for_voting(event_id, current_round=None):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    if current_round:
        c.execute('''
            SELECT songs.id, songs.title, songs.artist
            FROM songs
            JOIN event_songs ON songs.id = event_songs.song_id
            WHERE event_songs.event_id = ? AND event_songs.round_id = ?
        ''', (event_id, current_round))
    else:
        c.execute('''
            SELECT songs.id, songs.title, songs.artist
            FROM songs
            JOIN event_songs ON songs.id = event_songs.song_id
            WHERE event_songs.event_id = ?
        ''', (event_id,))
    
    songs = c.fetchall()
    conn.close()
    return songs

# Function to submit votes to the database
def submit_votes(user_name, event_id, round_id, selected_songs):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    for song_id in selected_songs:
        # Check if the user has already voted for this song in this round
        c.execute('''
            SELECT COUNT(*) FROM votes WHERE user_id = ? AND song = ? AND event_id = ? AND round_id = ?
        ''', (user_name, song_id, event_id, round_id))
        vote_exists = c.fetchone()[0]

        if not vote_exists:
            # Insert the vote into the database if the user hasn't voted for the song
            c.execute('''
                INSERT INTO votes (user_id, song, event_id, round_id, date)
                VALUES (?, ?, ?, ?, DATE('now'))
            ''', (user_name, song_id, event_id, round_id))

    conn.commit()
    conn.close()

# Splash screen for inactive voting
def display_splash_screen(message="No ongoing voting."):
    st.header("Vážení hosté,")
    st.subheader(message)
    st.write("📞 +420 608 462 008")
    st.write("✉️ [rudyhorvat77@gmail.com](mailto:rudyhorvat77@gmail.com)")
    st.divider()

# Voting page logic
def voting_page():
    # Fetch active event
    event = get_active_event()

    if not event:
        display_splash_screen("Aktuálně neprobíhá žádné hlasování.")
        return

    event_id, event_name, round_count, voting_active, current_round = event

    st.title(f"Vote for Your Favorite Songs - {event_name}")

    # User identification
    user_name = st.text_input("Enter your name to vote")

    if not user_name:
        st.warning("Please enter your name to vote.")
        return

    # Check if voting is active
    if not voting_active:
        st.warning("Voting is not active right now.")
        display_splash_screen("Aktuálně neprobíhá žádné hlasování.")
        return

    # Fetch the songs for voting (considering rounds if it's a multi-round event)
    if round_count > 1:
        songs = fetch_songs_for_voting(event_id, current_round)
        st.subheader(f"Round {current_round} Voting")
    else:
        songs = fetch_songs_for_voting(event_id)
        st.subheader("Single-Round Voting")

    if not songs:
        st.info("No songs available for voting.")
        return

    # Display song selection (max selection of 5)
    selected_songs = st.multiselect(
        "Select up to 5 songs:",
        options=[song[0] for song in songs],
        format_func=lambda x: f"{[song[1] for song in songs if song[0] == x][0]} by {[song[2] for song in songs if song[0] == x][0]}",
        max_selections=5
    )

    if st.button("Submit Vote"):
        if selected_songs:
            submit_votes(user_name, event_id, current_round, selected_songs)
            st.success(f"Thank you, {user_name}! You have successfully submitted your vote for {len(selected_songs)} songs.")
        else:
            st.warning("Please select at least one song to submit your vote.")

# Main page
if __name__ == "__main__":
    st.set_page_config(page_title="Voting Page", page_icon="🎶")
    voting_page()