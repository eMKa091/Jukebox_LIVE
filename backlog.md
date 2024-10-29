# Current backlog:

- [ ]   Band page
            -   V admin pagi bude band page, a tam bude okno, do ktereho ja to napisu, normalne text
                ty si pica, nonono prave, Siri, stop writing. Filip stop writing. haha. 
                A z toho co ja tam napisu, to se bude mirrorovat na dalsi stranku (separe link??).

- [x]   !! Statuses from voting influences status for song management and that is not good.            
- [x]   !! When page is refreshed, st.session state is lost and that means reset to round 1 on song mgmgt.
- [x]   Show also date on event details (buttons, etc.)
- [x]   Introduce "limiter" to number of songs.
- [x]   Introduce another column "removed" BOOLEAN - change DB schema, change all fucking functions.
- [x]   Make list (color coded or delimited in other way) of songs for the event and rounds.
- [x]   Udelej take tlacitko - add (newly added or previously removed) songs to event (= diff if there is additional .csv uploaded)
- [x]   Remove time delay. 

Voting:
- [ ]   Optimis(z)e voting page for mobile device(s).
- [ ]   Number of round is not displayed correctly in voting page - needs to be reflected from voting setting (control) page.
- [ ]   Change from drop down (which is the best) to different shitty thing.


PANIKA
- [ ]   When user deletes all songs from DB, it breaks logic for managing songs,
        because the table is referenced:

        e.g. in song_management function:
            SELECT s.id, s.title, s.artist 
            FROM songs s 
            JOIN event_songs es ON s.id = es.song_id 
            WHERE es.event_id = ? AND es.played = 0

