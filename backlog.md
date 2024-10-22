Current backlog:

- [ ]   When user deletes all songs from DB, it breaks logic for managing songs
        because the table is referenced:

        e.g. in song_management function:
            SELECT s.id, s.title, s.artist 
            FROM songs s 
            JOIN event_songs es ON s.id = es.song_id 
            WHERE es.event_id = ? AND es.played = 0

