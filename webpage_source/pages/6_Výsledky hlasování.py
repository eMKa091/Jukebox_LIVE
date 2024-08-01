# pages/Overview.py
import streamlit as st
import pandas as pd
import os
from collections import Counter

st.set_page_config(page_title='Přehled')

st.header('Přehled oblíbených písní')

# Define the directory containing the vote results
results_dir = os.path.join("webpage_source", "vote_results")

# Initialize a Counter to aggregate song selections
song_counter = Counter()

# Iterate through all files in the results directory
for filename in os.listdir(results_dir):
    if filename.startswith("selected_songs_") and filename.endswith(".txt"):
        file_path = os.path.join(results_dir, filename)
        with open(file_path, "r") as file:
            songs = file.readlines()
            for song in songs:
                song_counter[song.strip()] += 1

# Convert the Counter to a DataFrame for easier manipulation
df_songs = pd.DataFrame(song_counter.items(), columns=["Píseň", "Počet hlasů"]).sort_values(by="Počet hlasů", ascending=False)

# Limit to the top 25 most popular songs
df_top_songs = df_songs.head(25)

# Reset the index and drop the old one
df_top_songs.index = range(1, len(df_top_songs) + 1)

# Display the top 25 songs in a clear table format
st.subheader("Top 25 nejoblíbenějších písní")
st.write("Níže je seznam top 25 písní podle počtu hlasů:")

# Display the table with top 25 songs without the index
st.table(df_top_songs)