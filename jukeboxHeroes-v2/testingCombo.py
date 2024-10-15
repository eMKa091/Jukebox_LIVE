import streamlit as st
import sqlite3

DATABASE = 'votes.db'

# Initialize database and create tables if needed
def init_db():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # Create events table
    c.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            round_count INTEGER,
            voting_active BOOLEAN,
            current_round INTEGER
        )
    ''')

    # Create votes table with the correct schema
    c.execute('''
        CREATE TABLE IF NOT EXISTS votes (
            user_id TEXT,
            song TEXT,
            event_id INTEGER,
            round_id INTEGER,
            date TEXT,
            FOREIGN KEY (event_id) REFERENCES events(id)
        )
    ''')

    conn.commit()
    conn.close()

def reset_votes_table():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # Drop the existing votes table if it exists
    c.execute('DROP TABLE IF EXISTS votes')

    # Recreate the votes table with the correct schema
    c.execute('''
        CREATE TABLE votes (
            user_id TEXT,
            song TEXT,
            event_id INTEGER,
            round_id INTEGER,
            date TEXT,
            FOREIGN KEY (event_id) REFERENCES events(id)
        )
    ''')

    conn.commit()
    conn.close()

# Create a new event
def create_event(name, round_count):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('INSERT INTO events (name, round_count, voting_active, current_round) VALUES (?, ?, ?, ?)', (name, round_count, True, 1))
    conn.commit()
    event_id = c.lastrowid
    conn.close()
    return event_id

# Fetch event details
def get_event_details(event_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('SELECT name, round_count, voting_active, current_round FROM events WHERE id = ?', (event_id,))
    event = c.fetchone()
    conn.close()
    return event

# Submit votes
def submit_votes(user_name, event_id, round_id, selected_songs):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    for song in selected_songs:
        c.execute('INSERT INTO votes (user_id, song, event_id, round_id, date) VALUES (?, ?, ?, ?, DATE("now"))', (user_name, song, event_id, round_id))
    conn.commit()
    conn.close()

# Voting Page Logic
def voting_page(event_id):
    st.title("Voting Page")

    # Fetch event details
    event_details = get_event_details(event_id)
    if not event_details:
        st.error("Event not found!")
        return

    event_name, round_count, voting_active, current_round = event_details

    # If voting is not active, display a message
    if not voting_active:
        st.warning("Voting is not active.")
        return

    st.subheader(f"Vote for {event_name} (Round {current_round})")

    # User identification
    if 'user_name' not in st.session_state:
        st.session_state['user_name'] = st.text_input("Enter your name to vote")

        if st.button("Submit Name"):
            if not st.session_state['user_name']:
                st.warning("Please enter your name.")
                return
            st.success(f"Welcome, {st.session_state['user_name']}!")

    if 'user_name' in st.session_state:
        # Display the voting options (simplified for this example)
        songs = ["Song 1", "Song 2", "Song 3", "Song 4", "Song 5"]
        selected_songs = st.multiselect("Select up to 5 songs", options=songs, max_selections=5)

        if st.button("Submit Vote"):
            if selected_songs:
                submit_votes(st.session_state['user_name'], event_id, current_round, selected_songs)
                st.success(f"Thank you for voting, {st.session_state['user_name']}!")
            else:
                st.warning("Please select at least one song.")

# Admin Page Logic
def admin_page():
    st.title("Admin Page - Create Event and Start Voting")

    # Admin creates an event
    event_name = st.text_input("Enter event name")
    round_count = st.number_input("Enter number of rounds", min_value=1, max_value=10, value=1)
    
    if st.button("Create Event"):
        if event_name:
            event_id = create_event(event_name, round_count)
            st.session_state['active_event_id'] = event_id
            st.success(f"Event '{event_name}' created and voting started!")
        else:
            st.warning("Please enter an event name.")
    
    # If an event is created, proceed to the voting page
    if 'active_event_id' in st.session_state:
        voting_page(st.session_state['active_event_id'])

# Main App Logic
def main():
    init_db()
    reset_votes_table()
    
    # Simple navigation between admin and voting page
    if 'current_page' not in st.session_state:
        st.session_state['current_page'] = 'admin'

    if st.session_state['current_page'] == 'admin':
        admin_page()

if __name__ == "__main__":
    main()
