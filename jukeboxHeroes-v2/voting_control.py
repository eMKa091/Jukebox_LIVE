import sqlite3
import streamlit as st
from database import update_voting_state

DATABASE = 'votes.db'

#############################
# Single-Round Voting Logic #
#############################
def manage_single_round(event_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # Fetch the current voting state from the database
    c.execute('SELECT voting_active FROM events WHERE id = ?', (event_id,))
    voting_active = c.fetchone()[0]
    conn.close()

    # Display current voting status
    if voting_active:
        st.success("Voting is currently active.")
        if st.button("Stop Voting"):
            update_voting_state(event_id, False)  # Stop voting for this event
            st.write("Voting stopped.")
            st.rerun()
    else:
        st.warning("Voting is currently stopped.")
        if st.button("Start Voting"):
            update_voting_state(event_id, True)  # Start voting, stop all other active events
            st.success("Voting started!")
            st.session_state['active_event_id'] = event_id  # Store event ID for the voting page
            st.rerun()

############################
# Multi-Round Voting Logic #
############################
def manage_rounds(event_id, round_count):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # Fetch the current round and voting state from the database
    c.execute('SELECT voting_active, current_round FROM events WHERE id = ?', (event_id,))
    voting_active, current_round = c.fetchone()
    conn.close()

    if current_round > round_count:
        st.write("All rounds are completed.")
        display_splash_screen(f"All voting rounds completed.")
        return

    # Display current round info
    st.write(f"**Current Round: {current_round}/{round_count}**")

    # Voting control for the current round
    if voting_active:
        st.success(f"Voting for Round {current_round} is active.")
        if st.button("Stop Voting"):
            update_voting_state(event_id, False, current_round + 1)  # Stop current round voting
            st.write(f"Voting for Round {current_round} stopped.")
            st.rerun()
    else:
        st.warning(f"Voting for Round {current_round} is currently stopped.")
        if st.button(f"Start Voting for Round {current_round}"):
            update_voting_state(event_id, True, current_round)  # Start voting, stop all other active events
            st.session_state['active_event_id'] = event_id
            st.success(f"Voting for Round {current_round} started!")
            st.rerun()

############################
# Voting Control Logic     #
############################
def voting_control(event_id, round_count):
    st.subheader("Voting")

    # Check if this is a multi-round event
    if round_count > 1:
        st.write(f"**Multi-round event with {round_count} rounds**")
        manage_rounds(event_id, round_count)
    else:
        st.write("**Single-round event**")
        manage_single_round(event_id)

############################
# Splash Screen Display    #
############################
def display_splash_screen(message="No ongoing voting."):
    st.subheader("Vážení hosté,")
    st.subheader(message)
    st.divider()
    st.subheader("Neváhejte nás kontaktovat:")
    st.write("📞 +420 608 462 008")
    st.write("✉️ [rudyhorvat77@gmail.com](mailto:rudyhorvat77@gmail.com)")
    st.image("./img/rudy.png")
    st.divider()
    if st.button(label="Admin page"):
        st.session_state['page'] = 'admin'
        st.rerun()
################################
# Submit votes to the database #
################################
def submit_votes(user_name, event_id, round_id, selected_songs):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    for song_id in selected_songs:
        # Check if the user has already voted for this song in this round
        c.execute('''
            SELECT COUNT(*) FROM votes WHERE user_id = ? AND song = ? AND event_id = ? AND round_id = ?
        ''', (user_name, song_id, event_id, round_id))
        vote_exists = c.fetchone()[0]

        # Insert the vote only if it doesn't already exist
        if not vote_exists:
            c.execute('''
                INSERT INTO votes (user_id, song, event_id, round_id, date)
                VALUES (?, ?, ?, ?, DATE('now'))
            ''', (user_name, song_id, event_id, round_id))

    conn.commit()
    conn.close()