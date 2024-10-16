import streamlit as st
import sqlite3
from database import (create_event, delete_event,add_voting_state_to_events, init_db)
from voting_control import *
from login_control import *
from song_control import *

DATABASE = 'votes.db'
init_db()
add_voting_state_to_events()

##############################
# EVENT MANAGEMENT FUNCTIONS #
##############################
def event_management():
    st.subheader("Create new event")

    # Event creation form
    with st.form(key='create_event_form'):
        new_event_name = st.text_input("Event Name")
        new_event_date = st.date_input("Event Date")
        new_event_rounds = st.number_input("Number of Rounds", min_value=1, max_value=10, value=1)
        create_event_button = st.form_submit_button("Create Event")

        # Handle event creation logic
        if create_event_button and new_event_name and new_event_date:
            event_id = create_event(new_event_name, str(new_event_date), new_event_rounds)
            st.success(f"Event '{new_event_name}' created with ID {event_id}")

    # Fetch all events (ID, name, and voting_active state)
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('SELECT id, name, voting_active FROM events')
    events = c.fetchall()
    conn.close()

    # If no events exist, prompt the user to create an event
    if not events:
        st.warning("No events found. Please create an event before proceeding.")
        return None

    st.divider()
    st.subheader("Delete existing events")

    # Display buttons to delete events dynamically
    for event in events:
        event_id, event_name, voting_active = event
        if st.button(f"Delete Event {event_name}", key=f"delete_{event_id}"):
            delete_event(event_id)
            st.success(f"Event '{event_name}' and all related data have been deleted.")
            st.rerun()  # Refresh to update the event list

    st.divider()

    # Dropdown to select an event (make sure event ID is selected, not the name)
    event_selection = st.selectbox(
        "Select Event to manage", 
        options=[(event[0], event[1]) for event in events],  # Return event ID and name as options
        format_func=lambda x: x[1]  # Show the event name in the dropdown
    )

    event_id = event_selection[0]  # Return the event ID, not the name
    return event_id

###################
# MAIN ADMIN PAGE #
###################
def admin_page():
    if 'logged_in' in st.session_state and st.session_state['logged_in']:
        st.title("Admin Dashboard")
        st.divider()
        
        #################
        # MANAGE EVENTS #
        #################
        event_id = event_management()

        if event_id:
            conn = sqlite3.connect(DATABASE)
            c = conn.cursor()
            c.execute('SELECT round_count FROM events WHERE id = ?', (event_id,))
            round_count = c.fetchone()[0]
            conn.close()

            #####################
            # VOTING MANAGEMENT #
            #####################
            voting_control(event_id, round_count)

            ###################
            # SONG MANAGEMENT #
            ###################
            song_management(event_id)  # Manage songs for the selected event
            upload_songs_csv()  # Upload new songs
        
        ##########
        # BACKUP #
        ##########
        def backup_data_section():
            st.divider()
            st.subheader("Data backup")
            export_votes_to_csv()

        backup_data_section()

        # Add a button to navigate to the voting page
        if st.button("Go to Voting Page"):
            st.session_state['page'] = 'voting'
            st.rerun()

    else:
        admin_login()

admin_page()