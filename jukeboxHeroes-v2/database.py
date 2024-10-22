import sqlite3
import streamlit as st
from hashlib import sha256

DATABASE = 'votes.db'

def init_db():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # Create 'events' table
    c.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            date TEXT,
            round_count INTEGER DEFAULT 1,
            current_round INTEGER DEFAULT 1,
            voting_active BOOLEAN DEFAULT 0  
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
            round_id INTEGER,
            played BOOLEAN DEFAULT 0,
            PRIMARY KEY (event_id, song_id, round_id),
            FOREIGN KEY (event_id) REFERENCES events(id),
            FOREIGN KEY (song_id) REFERENCES songs(id)
        )
    ''')

    conn.commit()
    conn.close()

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

def fetch_admin_user(username):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('SELECT * FROM admin_users WHERE username = ?', (username,))
    user = c.fetchone()
    conn.close()
    return user

def create_event(name, date, round_count):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # Insert the new event
    c.execute('''
        INSERT INTO events (name, date, round_count) 
        VALUES (?, ?, ?)
    ''', (name, date, round_count))
    event_id = c.lastrowid

    conn.commit()
    conn.close()
    return event_id

def create_round(event_id, round_number, description):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO rounds (event_id, round_number, description) 
        VALUES (?, ?, ?)
    ''', (event_id, round_number, description))
    conn.commit()
    conn.close()

def store_vote(uniqueID, randomNumber, song, event_id, round_id, date):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO votes (uniqueID, randomNumber, song, event_id, round_id, date)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (uniqueID, randomNumber, song, event_id, round_id, date))
    conn.commit()
    conn.close()

def fetch_votes(event_id, round_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        SELECT * FROM votes WHERE event_id = ? AND round_id = ?
    ''', (event_id, round_id))
    votes = c.fetchall()
    conn.close()
    return votes

def mark_song_as_played(song_id, event_id, round_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO played_songs (song_id, event_id, round_id, played) 
        VALUES (?, ?, ?, ?)
    ''', (song_id, event_id, round_id, True))
    conn.commit()
    conn.close()

def fetch_played_songs(event_id, round_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        SELECT * FROM played_songs WHERE event_id = ? AND round_id = ? AND played = 1
    ''', (event_id, round_id))
    played_songs = c.fetchall()
    conn.close()
    return played_songs

def add_song(title, artist):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # Check if the song already exists in the database
    c.execute('''
        SELECT COUNT(*) FROM songs WHERE title = ? AND artist = ?
    ''', (title, artist))
    if c.fetchone()[0] > 0:
        # Song already exists, skip insertion
        conn.close()
        return False

    # Insert the new song if it doesn't exist
    c.execute('''
        INSERT INTO songs (title, artist)
        VALUES (?, ?)
    ''', (title, artist))
    
    conn.commit()
    conn.close()
    
    return True  # Return True to indicate the song was successfully added

def assign_song_to_event(event_id, song_id, round_id=None):
    """
    Assigns a song to an event in a specific round, checking for duplicates.
    """
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()

        # Fetch the song title for display purposes
        c.execute('SELECT title FROM songs WHERE id = ?', (song_id,))
        song = c.fetchone()
        song_title = song[0] if song else "Unknown Song"

        # Check if the song is already assigned to the event and round
        c.execute('''
            SELECT COUNT(*) FROM event_songs 
            WHERE event_id = ? AND song_id = ? AND round_id = ?
        ''', (event_id, song_id, round_id))
        if c.fetchone()[0] > 0:
            # Song is already assigned to this event and round
            return False  # No need to insert again

        # Insert the song if no duplicates are found
        try:
            c.execute('INSERT INTO event_songs (event_id, song_id, round_id) VALUES (?, ?, ?)', 
                      (event_id, song_id, round_id))
            conn.commit()
            return True  # Success
        except sqlite3.OperationalError as e:
            st.error(f"Error assigning song: {e}")
        except sqlite3.IntegrityError as e:
            st.error(f"Integrity Error: {e}")
        return False  # Failure

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
    """Remove a song from an event."""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("DELETE FROM event_songs WHERE event_id = ? AND song_id = ?", (event_id, song_id))
    conn.commit()
    conn.close()

def delete_event(event_id):
    """
    Deletes an event from the database and all related entries (event_songs, votes).
    """
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    try:      
        # Check if the event exists in the votes table
        #c.execute('SELECT * FROM votes WHERE event_id = ?', (event_id,))
        #votes_for_event = c.fetchall()
        #st.write(f"Votes for event: {votes_for_event}")
        
        # Check if the event exists in the event_songs table
        #c.execute('SELECT * FROM event_songs WHERE event_id = ?', (event_id,))
        #songs_for_event = c.fetchall()
        
        # Delete songs associated with the event
        c.execute('DELETE FROM event_songs WHERE event_id = ?', (event_id,))

        # Delete votes associated with the event
        c.execute('DELETE FROM votes WHERE event_id = ?', (event_id,))

        # Finally, delete the event itself
        c.execute('DELETE FROM events WHERE id = ?', (event_id,))

        conn.commit()
        st.success(f"Event {event_id} and all related data have been deleted.")
    except sqlite3.OperationalError as e:
        st.error(f"Error deleting event {event_id}: {e}")
    finally:
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
    Ensures only one event is active at any given time and provides a message if an active event is stopped.
    """
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # Check if any other event is currently active
    c.execute('SELECT id, name FROM events WHERE voting_active = 1 AND id != ?', (event_id,))
    other_active_event = c.fetchone()

    if voting_active and other_active_event:
        # Stop any other active event
        other_event_id, other_event_name = other_active_event
        c.execute('UPDATE events SET voting_active = 0 WHERE id = ?', (other_event_id,))
        st.warning(f"Voting for '{other_event_name}' was stopped as you started voting for another event.")

    # Update the voting state for the current event
    if current_round:
        c.execute('''
            UPDATE events SET voting_active = ?, current_round = ? WHERE id = ?
        ''', (voting_active, current_round, event_id))
    else:
        c.execute('''
            UPDATE events SET voting_active = ? WHERE id = ?
        ''', (voting_active, event_id))

    conn.commit()
    conn.close()

def start_voting(event_id, round_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    
    # Update the event to mark voting as active
    c.execute('''UPDATE events SET voting_active = 1 WHERE id = ?''', (event_id,))
    
    # Additional logic for round-based voting if needed
    # You can use round_id for managing round-specific voting
    
    conn.commit()
    conn.close()

def stop_voting(event_id, round_id):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    
    # Update the event to mark voting as inactive
    c.execute('''UPDATE events SET voting_active = 0 WHERE id = ?''', (event_id,))
    
    conn.commit()
    conn.close()

def remove_all_songs():
    """
    Remove all songs from the 'songs' table.
    """
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    # Execute SQL to delete all rows in the songs table
    c.execute('DELETE FROM songs')

    # Commit changes and close the connection
    conn.commit()
    conn.close()

# Initialize the database when this module is run
if __name__ == "__main__":
    init_db()