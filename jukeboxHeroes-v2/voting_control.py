import sqlite3
import streamlit as st
from database import update_voting_state, stop_voting

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
            update_voting_state(event_id, False)
            st.write("Voting stopped.")
            st.rerun()
    else:
        st.warning("Voting is currently stopped.")
        if st.button("Start Voting"):
            update_voting_state(event_id, True)
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
            update_voting_state(event_id, False, current_round + 1)
            st.write(f"Voting for Round {current_round} stopped.")
            st.rerun()
    else:
        st.warning(f"Voting for Round {current_round} is currently stopped.")
        if st.button(f"Start Voting for Round {current_round}"):
            update_voting_state(event_id, True)
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
    st.header("Vážení hosté,")
    st.header(message)
    st.subheader("Neváhejte nás však kontaktovat:")
    st.write("📞 +420 608 462 008")
    st.write("✉️ [rudyhorvat77@gmail.com](mailto:rudyhorvat77@gmail.com)")
    st.divider()
