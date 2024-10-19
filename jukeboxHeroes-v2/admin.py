import streamlit as st
import sqlite3
from database import *
from song_control import *
from voting_control import *

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
    events = load_events()

    # Sidebar Menu for Navigation
    st.sidebar.title("Admin Menu")
    menu_selection = st.sidebar.radio("Go to", ["Band`s playlist overview", "Event Management", "Song Management", "Voting Control", "Data Backup", "Voting Page", "Band Section"])

    # Event Management Section
    if menu_selection == "Band`s playlist overview":
        
        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        # Step 1: Check if the table has any entries
        c.execute('SELECT COUNT(*) FROM songs')
        song_count = c.fetchone()[0]

        if song_count == 0:
            # Step 2: If no entries, display a warning
            st.warning("The 'songs' table has no entries!")
            st.info("Please upload songs you can play :)")
            
            # Upload new song list
            upload_songs_csv()
            
        else:
            # Step 3: If there are entries, display the content
            st.header("These are songs you can play in database:")
            c.execute('SELECT id, title, artist FROM songs')
            rows = c.fetchall()
            
            # Print the entries in a nice format
            for row in rows:
                id, title, artist = row
                st.markdown(f"- **Song:** {title}  \n"
                    f"  **Artist:** {artist}  \n"
                    f"  **Database ID:** {id}")

    elif menu_selection == "Event Management":
        st.title("Event Management")
        
        # Event creation form
        st.subheader("Create New Event")
        with st.form(key='create_event_form'):
            new_event_name = st.text_input("Event Name")
            new_event_date = st.date_input("Event Date")
            new_event_rounds = st.number_input("Number of Rounds", min_value=1, max_value=10, value=1)
            create_event_button = st.form_submit_button("Create Event")

            if create_event_button and new_event_name and new_event_date:
                event_id = create_event(new_event_name, str(new_event_date), new_event_rounds)
                st.success(f"Event '{new_event_name}' created with ID {event_id}")
                
                # Automatically assign all songs to the new event
                conn = sqlite3.connect(DATABASE)
                c = conn.cursor()
                c.execute("SELECT id FROM songs")
                songs_exist = c.fetchall()
                conn.close()
                
                if songs_exist:
                    add_all_songs_to_event(event_id)
                    st.success(f"All songs assigned to event '{new_event_name}' by default.")
                
                # Reload events after creation
                events = load_events()

        # Delete events
        st.subheader("Delete Existing Events")
        if not events:
            st.warning("No events found. Please create an event before proceeding.")
        else:
            for event_id, event_name in events:
                if st.button(f"Delete Event '{event_name}'", key=f"delete_{event_id}"):
                    delete_event(event_id)
                    st.rerun()

    # Song Management Section
    elif menu_selection == "Song Management":
        st.title("Song Management")
        
        # Upload new song list
        upload_songs_csv()
        
        # Manage event songs
        if events:
            st.subheader("Manage Event Songs")
            event_name_selected = st.selectbox("Select Event", [e[1] for e in events])
            event_id_selected = [e[0] for e in events if e[1] == event_name_selected][0]
            
            # Get number of rounds
            conn = sqlite3.connect(DATABASE)
            c = conn.cursor()
            c.execute("SELECT round_count FROM events WHERE id = ?", (event_id_selected,))
            round_count = c.fetchone()[0]
            conn.close()

            # Round selection - Remove "None" for single-round events
            if round_count == 1:
                round_id = 1  # Automatically select Round 1 if it's a single-round event
            else:
                round_id = st.selectbox("Select Round", list(range(1, round_count + 1)))

            # Expandable list of songs for the event/round
            st.subheader("Songs Assigned to Event")
            conn = sqlite3.connect(DATABASE)
            c = conn.cursor()
            
            # Fetch songs assigned to the event (and optionally, the round)
            if round_count == 1:
                c.execute('''SELECT songs.title, songs.artist 
                            FROM event_songs event_songs
                            JOIN songs songs ON event_songs.song_id = songs.id
                            WHERE event_songs.event_id = ? AND event_songs.round_id IS NULL''', (event_id_selected,))
            else:
                c.execute('''SELECT songs.title, songs.artist 
                            FROM event_songs event_songs
                            JOIN songs songs ON event_songs.song_id = songs.id
                            WHERE event_songs.event_id = ? AND (event_songs.round_id = ? OR event_songs.round_id IS NULL)''', 
                            (event_id_selected, round_id))
            
            songs = c.fetchall()
            conn.close()
            
            for title, artist in songs:
                with st.expander(f"{title} by {artist}"):
                    st.write(f"Title: {title}")
                    st.write(f"Artist: {artist}")
        else:
            st.warning("No events found. Please create an event first.")

    # Voting Control Section
    elif menu_selection == "Voting Control":
        st.title("Voting Control")
    
        if events:
            st.subheader("Start/Stop Voting")
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
                round_id = st.selectbox("Select Round for Voting", list(range(1, round_count + 1)))
            else:
                round_id = 1
            
            # Voting control buttons - only show one based on current voting state
            if voting_active:
                if st.button("Stop Voting"):
                    stop_voting(event_id_selected, round_id)
                    st.success(f"Voting stopped for event {event_name_selected}, round {round_id}.")
            else:
                if st.button("Start Voting"):
                    start_voting(event_id_selected, round_id)
                    st.success(f"Voting started for event {event_name_selected}, round {round_id}.")
                else:
                    st.warning("No events found. Please create an event first.")

    # Data Backup Section
    elif menu_selection == "Data Backup":
        st.title("Data Backup")
        st.subheader("Backup the database")
        
        # Backup functionality (simplified for demonstration purposes)
        if st.button("Backup Now"):
            with open(DATABASE, "rb") as file:
                st.download_button(label="Download Backup", data=file, file_name="votes_backup.db")

    elif menu_selection == "Voting Page":
        #if st.button("Go to Voting Page"):
        st.session_state['page'] = 'voting'
        st.rerun()

    elif menu_selection == "Band Section":
        #if st.button("Go to Band Section"):
        st.session_state['page'] = 'bandSection'
        st.rerun()