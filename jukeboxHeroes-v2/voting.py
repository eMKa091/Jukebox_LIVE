import streamlit as st
import sqlite3

DATABASE = 'votes.db'

##########################
# Fetch Event Details    #
##########################
def get_event_details(event_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('SELECT name, round_count, voting_active, current_round FROM events WHERE id = ?', (event_id,))
    event = c.fetchone()
    conn.close()
    return event if event else None

##########################
# Fetch Songs for Voting #
##########################
def fetch_songs_for_voting(event_id, current_round=None):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    if current_round:
        # Fetch songs for the current round in multi-round events
        c.execute('''
            SELECT songs.id, songs.title, songs.artist
            FROM songs
            JOIN event_songs ON songs.id = event_songs.song_id
            WHERE event_songs.event_id = ? AND event_songs.round_id = ?
        ''', (event_id, current_round))
    else:
        # Fetch all songs for single-round events
        c.execute('''
            SELECT songs.id, songs.title, songs.artist
            FROM songs
            JOIN event_songs ON songs.id = event_songs.song_id
            WHERE event_songs.event_id = ?
        ''', (event_id,))
    
    songs = c.fetchall()
    conn.close()
    return songs

##########################
# Submit User Votes      #
##########################
def submit_votes(user_name, event_id, round_id, selected_songs):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # Insert each selected song into the votes table
    for song_id in selected_songs:
        c.execute('''
            INSERT INTO votes (user_id, song, event_id, round_id, date)
            VALUES (?, ?, ?, ?, DATE('now'))
        ''', (user_name, song_id, event_id, round_id))

    conn.commit()
    conn.close()

##########################
# User Identification    #
##########################
def user_identification():
    if 'user_name' not in st.session_state:
        # Ask the user for their name
        st.subheader("Please enter your name to vote:")
        user_name = st.text_input("Enter your name")

        # Save the name in session state after submission
        if st.button("Submit"):
            if user_name:
                st.session_state['user_name'] = user_name
                st.success(f"Welcome, {user_name}!")
            else:
                st.warning("Please enter your name to continue.")

    else:
        st.success(f"Welcome back, {st.session_state['user_name']}!")

#####################
# Voting Page Logic #
#####################
def voting_page():
    # Add a button to navigate back to the admin page
    if st.button("Go to Admin Page"):
        st.session_state['page'] = 'admin'
        st.rerun()
    # Retrieve the event_id from session state or default to a valid one
    event_id = st.session_state.get("active_event_id", 1)

    # Fetch event details
    event_details = get_event_details(event_id)
    if not event_details:
        st.error("Event not found!")
        return

    event_name, round_count, voting_active, current_round = event_details

    st.title(f"Vote for Your Favorite Songs - {event_name}")

    # Check if the user is identified (i.e., their name is in session state)
    user_identification()
    
    if 'user_name' not in st.session_state:
        return  # Don't proceed until the user enters their name

    # Check if voting is active
    if not voting_active:
        st.warning("Voting is not active right now.")
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

    # Display the song selection (limit selection to 5 songs)
    selected_songs = st.multiselect(
        "Select up to 5 songs:",
        options=[song[0] for song in songs],
        format_func=lambda x: f"{songs[x][1]} by {songs[x][2]}",
        max_selections=5
    )

    if st.button("Submit Vote"):
        user_name = st.session_state['user_name']

        # Submit votes
        if selected_songs:
            submit_votes(user_name, event_id, current_round, selected_songs)
            st.success(f"Thank you, {user_name}! You selected {len(selected_songs)} songs.")
        else:
            st.warning("Please select at least one song.")

########
# Main #
########
if __name__ == "__main__":
    st.set_page_config(page_title="Voting Page", page_icon="🎶")

    # Assuming we have an event running, otherwise redirect to splash screen
    if 'active_event_id' not in st.session_state:
        st.session_state['active_event_id'] = 1  # Set a default event ID for now

voting_page()