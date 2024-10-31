import sqlite3
import streamlit as st
from voting_control import display_splash_screen, submit_votes
from song_control import fetch_songs_for_voting

DATABASE = 'votes.db'

def get_active_event():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('SELECT id, name, round_count, voting_active, current_round FROM events WHERE voting_active = 1')
    event = c.fetchone()
    conn.close()
    return event if event else None

def voting_page():
    # Fetch active event
    event = get_active_event()
    if not event:
        display_splash_screen("Aktuálně neprobíhá žádné hlasování.")
        return

    event_id, event_name, round_count, voting_active, current_round = event
    st.title(f"Vote for your favorite songs")

    # User identification
    user_name = st.text_input("First, enter your name to vote")
    if not user_name:
        st.warning("Please enter your name to vote.")
        return

    # Initialize voting status tracking for this event and user if not already done
    if 'voted_rounds' not in st.session_state:
        st.session_state['voted_rounds'] = {}

    # Check if the user has already voted in the current round
    if event_id in st.session_state['voted_rounds'] and current_round in st.session_state['voted_rounds'][event_id]:
        st.success("Thank you for voting in this round!")
        return

    # Fetch the songs for the current round
    songs = fetch_songs_for_voting(event_id)
    if not songs:
        st.info("No songs available for voting.")
        return

    st.subheader(f"Voting for Round {current_round}")

    # Fetch max votes for the current round
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT max_votes FROM rounds WHERE event_id = ? AND round_number = ?", (event_id, current_round))
    max_votes_result = c.fetchone()
    current_max_votes = max_votes_result[0] if max_votes_result else 5
    conn.close()

    # Track selected songs and flag for when limit is reached
    selected_songs = []  # List to store selected song IDs
    selected_count = 0  # Count of currently selected songs
    limit_reached = False  # Flag to indicate if max selection limit is reached

    # Inform user of the maximum selection allowed
    st.write(f"Select up to {current_max_votes} songs:")

    # Display checkboxes for each song
    for song_id, song_title, artist in songs:
        # Disable further checkboxes if limit is reached
        if selected_count >= current_max_votes:
            limit_reached = True  # Set flag to show warning once after loop
            is_selected = False
        else:
            is_selected = st.checkbox(f"{song_title} by {artist}", key=song_id)

        # Add song to selected list if checked
        if is_selected:
            selected_songs.append(song_id)
            selected_count += 1

    # Show warning only once if limit has been reached
    if limit_reached:
        st.warning(f"You've reached the maximum of {current_max_votes} selections.")

    # Submit vote button
    if st.button("Submit Vote"):
        if selected_songs:
            submit_votes(user_name, event_id, current_round, selected_songs)
            if event_id not in st.session_state['voted_rounds']:
                st.session_state['voted_rounds'][event_id] = []
            st.session_state['voted_rounds'][event_id].append(current_round)
            st.success(f"Thank you, {user_name}! You have successfully submitted your vote for {len(selected_songs)} songs.")
            st.balloons()  # Optional celebration
            st.rerun()  # Rerun to clear selections
        else:
            st.warning("Please select at least one song to submit your vote")

# Main page
if __name__ == "__main__":
    st.set_page_config(page_title="Voting Page", page_icon="🎶")
    voting_page()