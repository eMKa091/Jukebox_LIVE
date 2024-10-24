import streamlit as st
import sqlite3
import time
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

                st.divider()    
                st.warning(":warning: Do not delete songs if you have any events to manage")
                if st.button("Delete all songs from DB"):
                    remove_all_songs()
                    st.rerun()
                
                upload_songs_csv()
                if st.button("Add to DB (only refreshes page in reality"):
                    st.rerun()

####################
# EVENT MANAGEMENT #
####################
        elif menu_selection == "Event Management":
            tab1, tab2 = st.tabs([":new: Create new event", ":x: Delete events"])
            
            conn = sqlite3.connect(DATABASE)
            c = conn.cursor()
            c.execute("SELECT id FROM songs")
            songs_exist = c.fetchall()
            conn.close()
            
            if songs_exist:
                with tab1:
                    # Event creation form
                    with st.form(key='create_event_form'):
                        new_event_name = st.text_input("Event name")
                        new_event_date = st.date_input("Event date")
                        new_event_rounds = st.number_input("Number of rounds", min_value=1, max_value=10, value=1)
                        create_event_button = st.form_submit_button("Create event")

                        if create_event_button and new_event_name and new_event_date:
                            event_id = create_event(new_event_name, str(new_event_date), new_event_rounds)
                            st.success(f"Event '{new_event_name}' created with ID {event_id}")

                            if new_event_rounds == 1:
                            # Add all songs to the event
                                add_all_songs_to_event(event_id)
                                st.success(f"All songs assigned to event by default.")
                                time.sleep(2)

                            else:
                                round_id = 1
                                add_all_songs_to_event(event_id, round_id)
                                st.success(f"All songs assigned to first round by default.")
                                time.sleep(2)
                            
                            # Reload events after creation
                            events = load_events()
            else:
                st.subheader("Create new events", divider=True)
                st.info(":flashlight: Please upload song list first to create new event")
                st.write("")
                st.write("")
                st.write("")

            if not events:
                st.info(":flashlight: There are no previously created events")
            else:
                with tab2:
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
                
                # Use session state to manage the rounds for each event
                event_round_key = f'round_id_{event_id_selected}'
                
                if event_round_key not in st.session_state:
                    st.session_state[event_round_key] = 1  # Default to round 1 for each event

                # Call the song_management function with the event's specific round_id
                song_management(event_id_selected, st.session_state[event_round_key])
                
            else:
                st.info(":flashlight: Please create an event first")


##################
# VOTING CONTROL #
##################
        elif menu_selection == "Voting Control":           
            if events:
                st.subheader(":wrench: Manage Voting", divider=True)
                event_name_selected = st.selectbox("Select event", [e[1] for e in events])
                event_id_selected = [e[0] for e in events if e[1] == event_name_selected][0]

                # Get the number of rounds, current round, round status, and voting state from the database
                conn = sqlite3.connect(DATABASE)
                c = conn.cursor()
                c.execute("SELECT round_count, current_round, voting_active, round_status FROM events WHERE id = ?", (event_id_selected,))
                round_count, current_round, voting_active, round_status = c.fetchone()
                conn.close()

                st.info(f"This is a multi-round event. You are currently in **Round {current_round}**.")

                # Create tabs for each round
                tabs = st.tabs([f"Round {i}" for i in range(1, round_count + 1)])

                for i in range(1, round_count + 1):
                    with tabs[i - 1]:
                        if i == current_round:
                            # Show voting control for the current round
                            if voting_active:
                                if st.button("Stop voting"):
                                    stop_voting(event_id_selected, current_round)
                                    st.success(f"Voting stopped for event '{event_name_selected}', round {current_round}.")
                                    
                                    # Update the round status to 'completed' in the database
                                    conn = sqlite3.connect(DATABASE)
                                    c = conn.cursor()
                                    c.execute("UPDATE events SET round_status = 'completed' WHERE id = ?", (event_id_selected,))
                                    conn.commit()
                                    conn.close()
                                    st.rerun()

                            elif round_status == 'completed':
                                # Voting is already completed for the current round
                                st.info(f"Voting for round {current_round} is completed.")
                            else:
                                if st.button("Start voting"):
                                    # Start voting and update the status to 'ongoing'
                                    start_voting(event_id_selected, current_round)
                                    
                                    conn = sqlite3.connect(DATABASE)
                                    c = conn.cursor()
                                    c.execute("UPDATE events SET round_status = 'ongoing' WHERE id = ?", (event_id_selected,))
                                    conn.commit()
                                    conn.close()

                                    st.success(f"Voting started for event '{event_name_selected}', round {current_round}.")
                                    st.rerun()

                            # Show "Move to Next Round" button after voting has started or stopped
                            if not voting_active or round_status == 'completed':
                                if current_round < round_count:
                                    if round_status == 'completed':
                                        if st.button("Move to Next Round", key=f"next_round_{event_id_selected}_{current_round}"):
                                            next_round = current_round + 1
                                            # Update the current round and round status in the database
                                            conn = sqlite3.connect(DATABASE)
                                            c = conn.cursor()
                                            c.execute("UPDATE events SET current_round = ?, round_status = 'not_started' WHERE id = ?", (next_round, event_id_selected))
                                            conn.commit()
                                            conn.close()

                                            # Automatically switch to the next round tab
                                            st.rerun()

                            # Mark last round in DB
                            if current_round == round_count:
                                conn = sqlite3.connect(DATABASE)
                                c = conn.cursor()
                                c.execute("UPDATE events SET last_round = True")
                                conn.commit()
                                conn.close()

                                st.info(f"This is the last round")
                                #st.markdown(f":tada: **Event '{event_name_selected}' is complete. No more rounds available.**")

                            if last_round 

                        # Past rounds: Only show that the round is completed
                        elif i < current_round:
                            st.info(f"Round {i} is completed.")

                        # Future rounds: Show both that the round is upcoming and current round is ongoing
                        else:
                            st.warning(f"Current round is {current_round}. You cannot interact with Round {i} until the current round is completed.")
                            st.info(f"Round {i} is upcoming.")

            else:
                st.info(":flashlight: Please create an event first")

#####################
# BACKUP OPERATIONS #
#####################
        elif menu_selection == "Data Backup":
            st.subheader(":back: :up: the database")
            
            # Backup functionality (simplified for demonstration purposes)
            if st.button("Backup now"):
                with open(DATABASE, "rb") as file:
                    st.download_button(label="Download backup", data=file, file_name="votes_backup.db")

############################
# NAVIGATION - VOTING PAGE #
###################if#########
        elif menu_selection == "Voting Page":
            #if st.button("Go to Voting Page"):
            st.session_state['page'] = 'voting'
            st.rerun()
    else:
        admin_login()