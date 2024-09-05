import streamlit as st
import pandas as pd
import sqlite3
from random import randint
from datetime import datetime

# Clear votes in the database
def clear_votes():
    conn = sqlite3.connect('votes.db')
    c = conn.cursor()
    
    # Delete all records from the votes table
    c.execute('DELETE FROM votes')
    
    # Commit the changes and close the connection
    conn.commit()
    conn.close()

# Reset the database by recreating the votes table with the correct schema
def reset_db():
    conn = sqlite3.connect('votes.db')
    c = conn.cursor()

    # Drop the table if it exists
    c.execute('DROP TABLE IF EXISTS votes')

    # Recreate the table with the correct schema
    c.execute('''
        CREATE TABLE votes (
            uniqueID TEXT,
            randomNumber INTEGER,
            song TEXT,
            date TEXT
        )
    ''')
    
    conn.commit()
    conn.close()

# Function to show the admin page with top 10 most voted songs
def admin_page():
    st.title("Admin Wall")
    st.write("This is a restricted page for admin use only.")

    # Connect to the database
    conn = sqlite3.connect('votes.db')
    c = conn.cursor()

    # Query to get votes per date
    query = '''
    SELECT date, song, COUNT(song) as vote_count
    FROM votes
    GROUP BY date, song
    ORDER BY date, vote_count DESC
    '''
    df = pd.read_sql_query(query, conn)
    conn.close()

    # Aggregate top 10 songs across all dates
    df = df.groupby('date').apply(lambda x: x.nlargest(10, 'vote_count')).reset_index(drop=True)

    # Display the top 10 songs
    st.write("**Top 10 Songs Per Day**")
    if not df.empty:
        for date in df['date'].unique():
            st.subheader(f"Date: {date}")
            top_songs = df[df['date'] == date]
            for i, row in enumerate(top_songs.itertuples(), 1):
                st.write(f"{i}. {row.song} - {row.vote_count} votes")
            st.divider()
    else:
        st.write("No votes have been recorded yet.")

    # Buttons for clearing votes and resetting the database
    if st.button("Clear All Votes"):
        clear_votes()
        st.success("All votes have been cleared.")

    if st.button("Reset DB"):
        reset_db()
        st.success("Table was reset.")

# Function to show the main page for regular users
def main_page():
    # Check if the user is already in the session state
    if 'uniqueID' in st.session_state:
        st.success(f"Vítej zpět, {st.session_state.uniqueID}!")
        st.write("Tvou přezdívku už známe - hlasovat můžeš pouze jednou.")
        st.button("Pokračovat na hlasování", on_click=lambda: st.switch_page("Hlasovani"))

    # Show the welcome screen for new users
    else:
        st.header('Dobrý den, vážený hoste!')
        st.subheader("Vítej v aplikaci Jukebox Heroes!")
        st.write("Dnes máš jedinečnou možnost podílet se na tvorbě playlistu.")
        st.write("Ty písně, které budou mít nejvíce hlasů, zařadíme do playlistu.")
        
        st.divider()

        st.write('Zadej prosím svou přezdívku')
        uniqueID = st.text_input(label="Jméno či přezdívka", label_visibility='hidden')

        # Once the user provides a name, store it and redirect to voting
        if uniqueID:
            st.session_state.uniqueID = uniqueID
            st.session_state.randomNumber = randint(1, 100)
            st.success("Uloženo! Přesuneme vás na hlasování...")
            st.query_params.clear  # Clear any query params before switching pages
            st.switch_page("pages/Hlasování.py")  # Make sure the file name matches exactly

# Get the query parameters using the new API
params = st.query_params  # st.query_params returns a dictionary-like object

# Check if 'admin' query parameter exists and render the correct page
if 'admin' in params and params['admin'] == 'True':  # Compare directly to string 'True'
    admin_page()
else:
    main_page()
