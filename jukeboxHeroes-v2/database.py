import sqlite3
import streamlit as st
from hashlib import sha256

DATABASE = 'votes.db'

# Function to initialize or update the entire database schema
def init_db():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # Create 'events' table
    c.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            date TEXT,
            round_count INTEGER
        )
    ''')

    # Create 'rounds' table
    c.execute('''
        CREATE TABLE IF NOT EXISTS rounds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER,
            round_number INTEGER,
            description TEXT,
            FOREIGN KEY (event_id) REFERENCES events(id)
        )
    ''')

    # Create 'votes' table
    c.execute('''
        CREATE TABLE IF NOT EXISTS votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            song TEXT,
            event_id INTEGER,
            round_id INTEGER,
            date TEXT,
            FOREIGN KEY (event_id) REFERENCES events(id),
            FOREIGN KEY (round_id) REFERENCES rounds(id)
        )
    ''')

    # Create 'played_songs' table
    c.execute('''
        CREATE TABLE IF NOT EXISTS played_songs (
            song_id INTEGER,
            event_id INTEGER,
            round_id INTEGER,
            played BOOLEAN,
            PRIMARY KEY (song_id, event_id, round_id),
            FOREIGN KEY (event_id) REFERENCES events(id),
            FOREIGN KEY (round_id) REFERENCES rounds(id)
        )
    ''')

    # Create 'admin_users' table for admin authentication
    c.execute('''
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password_hash TEXT,
            role TEXT
        )
    ''')

    # Create 'admin_settings' table for storing admin-controlled settings
    c.execute('''
        CREATE TABLE IF NOT EXISTS admin_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT
        )
    ''')

    # Create 'songs' table to store song details
    c.execute('''
        CREATE TABLE IF NOT EXISTS songs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            artist TEXT
        )
    ''')

    # Create 'event_songs' table to link songs to events
    c.execute('''
        CREATE TABLE IF NOT EXISTS event_songs (
            event_id INTEGER,
            song_id INTEGER,
            PRIMARY KEY (event_id, song_id),
            FOREIGN KEY (event_id) REFERENCES events(id),
            FOREIGN KEY (song_id) REFERENCES songs(id)
        )
    ''')

    conn.commit()
    conn.close()

# Function to add an admin user (with hashed password)
def add_admin_user(username, password):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # Hash the password using sha256 (can be replaced with bcrypt or similar)
    password_hash = sha256(password.encode()).hexdigest()

    try:
        c.execute('''
            INSERT INTO admin_users (username, password_hash, role) 
            VALUES (?, ?, ?)
        ''', (username, password_hash, 'admin'))
        conn.commit()
    except sqlite3.IntegrityError:
        print("Error: Admin user already exists.")
    finally:
        conn.close()

# Function to fetch an admin user by username
def fetch_admin_user(username):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('SELECT * FROM admin_users WHERE username = ?', (username,))
    user = c.fetchone()
    conn.close()
    return user

# Function to create a new event
def create_event(name, date, round_count):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO events (name, date, round_count) 
        VALUES (?, ?, ?)
    ''', (name, date, round_count))
    event_id = c.lastrowid

    # Automatically assign all songs to the new event
    c.execute('SELECT id FROM songs')  # Get all song IDs from the songs table
    all_songs = c.fetchall()

    for song in all_songs:
        song_id = song[0]
        c.execute('''
            INSERT INTO event_songs (event_id, song_id)
            VALUES (?, ?)
        ''', (event_id, song_id))

    conn.commit()
    conn.close()
    return event_id

# Function to create rounds for an event
def create_round(event_id, round_number, description):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO rounds (event_id, round_number, description) 
        VALUES (?, ?, ?)
    ''', (event_id, round_number, description))
    conn.commit()
    conn.close()

# Function to store a vote
def store_vote(uniqueID, randomNumber, song, event_id, round_id, date):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO votes (uniqueID, randomNumber, song, event_id, round_id, date)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (uniqueID, randomNumber, song, event_id, round_id, date))
    conn.commit()
    conn.close()

# Function to retrieve votes for an event and round
def fetch_votes(event_id, round_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        SELECT * FROM votes WHERE event_id = ? AND round_id = ?
    ''', (event_id, round_id))
    votes = c.fetchall()
    conn.close()
    return votes

# Function to mark a song as played
def mark_song_as_played(song_id, event_id, round_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO played_songs (song_id, event_id, round_id, played) 
        VALUES (?, ?, ?, ?)
    ''', (song_id, event_id, round_id, True))
    conn.commit()
    conn.close()

# Function to retrieve played songs for a round
def fetch_played_songs(event_id, round_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        SELECT * FROM played_songs WHERE event_id = ? AND round_id = ? AND played = 1
    ''', (event_id, round_id))
    played_songs = c.fetchall()
    conn.close()
    return played_songs

# Function to add a new song to the songs table
def add_song(title, artist):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO songs (title, artist)
        VALUES (?, ?)
    ''', (title, artist))
    song_id = c.lastrowid
    conn.commit()
    conn.close()
    return song_id

# Function to assign a song to an event (event_songs table)
def assign_song_to_event(event_id, song_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO event_songs (event_id, song_id)
        VALUES (?, ?)
    ''', (event_id, song_id))
    conn.commit()
    conn.close()

# Function to retrieve all songs for a specific event
def get_songs_for_event(event_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        SELECT songs.id, songs.title, songs.artist
        FROM songs
        JOIN event_songs ON songs.id = event_songs.song_id
        WHERE event_songs.event_id = ?
    ''', (event_id,))
    songs = c.fetchall()
    conn.close()
    return songs

# Function to update song details
def update_song(song_id, title, artist):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        UPDATE songs
        SET title = ?, artist = ?
        WHERE id = ?
    ''', (title, artist, song_id))
    conn.commit()
    conn.close()

def remove_song_from_event(event_id, song_id):
    """
    Completely removes a song from the event by deleting the entry from the event_songs table.
    """
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        DELETE FROM event_songs WHERE event_id = ? AND song_id = ?
    ''', (event_id, song_id))
    conn.commit()
    conn.close()

def delete_event(event_id):
    """
    Deletes an event from the database and all related entries (event_songs, votes).
    """
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    try:
        st.write(f"Attempting to delete event with ID: {event_id}")
        
        # Check if the event exists in the votes table
        c.execute('SELECT * FROM votes WHERE event_id = ?', (event_id,))
        votes_for_event = c.fetchall()
        st.write(f"Votes for event: {votes_for_event}")
        
        # Check if the event exists in the event_songs table
        c.execute('SELECT * FROM event_songs WHERE event_id = ?', (event_id,))
        songs_for_event = c.fetchall()
        st.write(f"Songs for event: {songs_for_event}")
        
        # Delete songs associated with the event
        c.execute('DELETE FROM event_songs WHERE event_id = ?', (event_id,))
        st.write("Deleted songs from event_songs")

        # Delete votes associated with the event
        c.execute('DELETE FROM votes WHERE event_id = ?', (event_id,))
        st.write("Deleted votes from votes")

        # Finally, delete the event itself
        c.execute('DELETE FROM events WHERE id = ?', (event_id,))
        st.write(f"Deleted event {event_id} from events table")

        conn.commit()
        st.success(f"Event {event_id} and all related data have been deleted.")
    except sqlite3.OperationalError as e:
        st.error(f"Error deleting event {event_id}: {e}")
    finally:
        conn.close()

def check_table_schema():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # Check schema for the votes table
    c.execute("PRAGMA table_info(votes)")
    votes_schema = c.fetchall()
    st.write("Votes Table Schema:")
    for column in votes_schema:
        st.write(column)

    # Check schema for the event_songs table
    c.execute("PRAGMA table_info(event_songs)")
    event_songs_schema = c.fetchall()
    st.write("Event Songs Table Schema:")
    for column in event_songs_schema:
        st.write(column)

    conn.close()

def get_event_name(event_id):
    """
    Fetch the event name based on the event_id.
    """
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('SELECT name FROM events WHERE id = ?', (event_id,))
    event_name = c.fetchone()
    conn.close()
    return event_name[0] if event_name else "Unknown Event"

def add_voting_state_to_events():
    """
    Adds the voting_active and current_round columns to the events table.
    """
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # Check if the columns already exist
    c.execute("PRAGMA table_info(events)")
    columns = [info[1] for info in c.fetchall()]

    if 'voting_active' not in columns:
        # Add voting_active and current_round columns to the events table
        c.execute('ALTER TABLE events ADD COLUMN voting_active BOOLEAN DEFAULT 0')
        c.execute('ALTER TABLE events ADD COLUMN current_round INTEGER DEFAULT 1')
        conn.commit()
        print("Added voting_active and current_round to events table.")

    conn.close()

def update_voting_state(event_id, voting_active, current_round=None):
    """
    Updates the voting state (voting_active) and optionally the current round for multi-round events.
    """
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    if current_round:
        # Update both voting_active and current_round for multi-round events
        c.execute('''
            UPDATE events SET voting_active = ?, current_round = ? WHERE id = ?
        ''', (voting_active, current_round, event_id))
    else:
        # Update only the voting_active state for single-round events
        c.execute('''
            UPDATE events SET voting_active = ? WHERE id = ?
        ''', (voting_active, event_id))

    conn.commit()
    conn.close()

# Initialize the database when this module is run
if __name__ == "__main__":
    init_db()