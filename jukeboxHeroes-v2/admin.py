import streamlit as st
import sqlite3
from database import *
from song_control import *
from voting_control import *
from login_control import admin_login

# Initialize the database
DATABASE = 'votes.db'
init_db()

# Load the events once and use throughout the app
def load_events():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("SELECT id, name FROM events")
    events = c.fetchall()
    conn.close()
    return events

def admin_page():
    if 'logged_in' in st.session_state and st.session_state['logged_in']:

        # Initialize events
        events = load_events()

        # Sidebar Menu for Navigation
        st.sidebar.title("Admin Menu")
        menu_selection = st.sidebar.radio("Go to", ["Master song list", "Event Management", "Song management for events", "Voting Control", "Data Backup", "Voting Page"])

##########################################################################
#                               PAGE BUILD                               #
##########################################################################
####################
#  SONGS - MASTER  #
####################
        if menu_selection == "Master song list":
            
            # Step 1: Check if the table has any entries
            conn = sqlite3.connect(DATABASE)
            c = conn.cursor()
            c.execute('SELECT COUNT(*) FROM songs')
            song_count = c.fetchone()[0]

            if song_count == 0:
                # Step 2: If no entries, display a warning
                st.info(":pencil: Upload songs you can play")
                
                # Upload new song list
                upload_songs_csv()
                if st.button("Add to DB (only refreshes page in reality"):
                    st.rerun()
                
            else:
                if st.button("Delete all songs from DB"):
                    remove_all_songs()
                    st.rerun()
                # Step 3: If there are entries, display the content
                c.execute('SELECT id, title, artist FROM songs')
                rows = c.fetchall()
                if rows:
                    # Display a header
                    st.header(":musical_note: These are songs in DB used as a master")

                    # Loop through each song and create an expander for it
                    for row in rows:
                        song_id, title, artist = row

                        # Create an expander for each song
                        with st.expander(f"{title} by {artist}"):
                            st.write(f"**ID**: {song_id}")
                            st.write(f"**Title**: {title}")
                            st.write(f"**Artist**: {artist}")
                else:
                    st.warning("No songs found in the database.")
                
                upload_songs_csv()
                if st.button("Add to DB (only refreshes page in reality"):
                    st.rerun()

####################
# EVENT MANAGEMENT #
####################
        elif menu_selection == "Event Management":
            
            conn = sqlite3.connect(DATABASE)
            c = conn.cursor()
            c.execute("SELECT id FROM songs")
            songs_exist = c.fetchall()
            conn.close()
            
            if songs_exist:
                # Event creation form
                st.subheader(":new: Create New Event", divider=True)
                with st.form(key='create_event_form'):
                    new_event_name = st.text_input("Event Name")
                    new_event_date = st.date_input("Event Date")
                    new_event_rounds = st.number_input("Number of Rounds", min_value=1, max_value=10, value=1)
                    create_event_button = st.form_submit_button("Create Event")

                    if create_event_button and new_event_name and new_event_date:
                        event_id = create_event(new_event_name, str(new_event_date), new_event_rounds)
                        st.success(f"Event '{new_event_name}' created with ID {event_id}")
                        
                        if new_event_rounds == 1:
                        # Add all songs to the event
                            add_all_songs_to_event(event_id)
                            st.success(f"All songs assigned to event by default.")
                        
                        else:
                            round_id = 1
                            add_all_songs_to_event(event_id, round_id)
                            st.success(f"All songs assigned to first round by default.")
                        
                        # Reload events after creation
                        events = load_events()

            else:
                st.subheader("Create new events", divider=True)
                st.info(":flashlight: Please upload song list first to create new event")
                st.write("")
                st.write("")
                st.write("")

            if not events:
                st.subheader("Manage existing events",divider=True)
                st.info(":flashlight: There are no previously created events")
            else:
                st.subheader(":x: Delete existing events", divider=True)
                for event_id, event_name in events:
                    if st.button(f"Delete event '{event_name}'", key=f"delete_{event_id}"):
                        delete_event(event_id)
                        st.rerun()


#############################
# SONG MANAGEMENT PER EVENT #
#############################
        elif menu_selection == "Song management for events":
        
            # Manage event songs
            if events:
                event_name_selected = st.selectbox("Select Event", [e[1] for e in events])
                event_id_selected = [e[0] for e in events if e[1] == event_name_selected][0]    
                
                # Get number of rounds
                conn = sqlite3.connect(DATABASE)
                c = conn.cursor()
                c.execute("SELECT round_count FROM events WHERE id = ?", (event_id_selected,))
                round_count = c.fetchone()[0]
                conn.close()

                # Use session state to manage the rounds
                if 'round_id' not in st.session_state:
                    st.session_state['round_id'] = 1  # Default to round 1

                # Call the song_management function with event_id and round_id
                song_management(event_id_selected, st.session_state['round_id'])
                
            else:
                st.info(":flashlight: Please create an event first")

##################
# VOTING CONTROL #
##################
        elif menu_selection == "Voting Control":
            
            if events:
                st.subheader(":wrench: Manage voting", divider=True)
                event_name_selected = st.selectbox("Select Event for Voting", [e[1] for e in events])
                event_id_selected = [e[0] for e in events if e[1] == event_name_selected][0]
                
                # Get the number of rounds for this event
                conn = sqlite3.connect(DATABASE)
                c = conn.cursor()
                c.execute("SELECT round_count, voting_active FROM events WHERE id = ?", (event_id_selected,))
                round_count, voting_active = c.fetchone()
                conn.close()

                # Select round for voting
                if round_count > 1:
                    round_id = st.selectbox("Select round for voting", list(range(1, round_count + 1)))
                else:
                    round_id = 1
                
                # Voting control buttons - only show one based on current voting state
                if voting_active:
                    if st.button("Stop Voting"):
                        stop_voting(event_id_selected, round_id)
                        st.success(f"Voting stopped for event {event_name_selected}, round {round_id}.")
                        st.rerun()
                else:
                    if st.button("Start Voting"):
                        start_voting(event_id_selected, round_id)
                        st.success(f"Voting started for event {event_name_selected}, round {round_id}.")
                        st.rerun()
            else:
                st.info(":flashlight: Please create an event first")

#####################
# BACKUP OPERATIONS #
#####################
        elif menu_selection == "Data Backup":
            st.subheader(":back: :up: the database")
            
            # Backup functionality (simplified for demonstration purposes)
            if st.button("Backup Now"):
                with open(DATABASE, "rb") as file:
                    st.download_button(label="Download Backup", data=file, file_name="votes_backup.db")

############################
# NAVIGATION - VOTING PAGE #
############################
        elif menu_selection == "Voting Page":
            #if st.button("Go to Voting Page"):
            st.session_state['page'] = 'voting'
            st.rerun()
    else:
        admin_login()