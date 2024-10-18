from voting_control import (display_splash_screen, submit_votes)
from song_control import fetch_songs_for_voting
import streamlit as st
import sqlite3

DATABASE = 'votes.db'

def get_active_event():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('SELECT id, name, round_count, voting_active, current_round FROM events WHERE voting_active = 1')
    event = c.fetchone()
    conn.close()
    return event if event else None

def get_event_details(event_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('SELECT name, round_count, voting_active, current_round FROM events WHERE id = ?', (event_id,))
    event = c.fetchone()
    conn.close()
    return event if event else None

def voting_page():
    if st.button(label="Admin page"):
        st.session_state['page'] = 'admin'
        st.rerun()

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
        st.title("Thank you for voting!")
        st.subheader(f"You have already voted in Round {current_round}.")
        return  # Prevent further voting in this round

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
            # Submit the vote
            submit_votes(user_name, event_id, current_round, selected_songs)

            # Mark this round as voted in session state
            if event_id not in st.session_state['voted_rounds']:
                st.session_state['voted_rounds'][event_id] = []
            st.session_state['voted_rounds'][event_id].append(current_round)

            # Show success message and prevent further voting in this round
            st.success(f"Thank you, {user_name}! You have successfully submitted your vote for {len(selected_songs)} songs.")
            st.balloons()  # Optional celebration

            # Rerun to clear the controls and show the thank you message
            st.rerun()
        else:
            st.warning("Please select at least one song to submit your vote")

# Main page
if __name__ == "__main__":
    st.set_page_config(page_title="Voting Page", page_icon="🎶")
    voting_page()