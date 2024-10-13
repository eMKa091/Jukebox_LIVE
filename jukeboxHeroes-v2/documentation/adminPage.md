## Admin Page Functionalities
1. Start General (One-Round) Voting
    -   Admin can create a one-round event.
    -   Admin sets a single round (round_count = 1), and songs can be voted on for this round.
    -   The round is open for voting, and votes are recorded for the event and round.

2. Start Multi-Round Voting
    -   Admin can create multi-round events.
    -   Admin specifies the number of rounds (round_count) when creating the event.
    -   Admin can start/stop voting for each round, and votes are recorded for specific rounds.
    -   Different song lists can be assigned to each round of the event.

3. Mark Played Songs
    -   After a round, the admin can mark certain songs as “played” in the database, ensuring they are not shown in future rounds.
    -   This is stored in the played_songs table, where played is set to TRUE for marked songs.

4. Manage Event-Specific Song Lists
    -   Admin can view, add, or remove songs for an event's setlist.
    -   Adding new songs: Admin can dynamically add songs (title + artist) to the songs table.
    -   Assigning songs to events: Songs are linked to events through the event_songs table.
    -   Each event has its own setlist, so different events can have different song lists.

5. Create and Manage Events
    -   Admin can create new events, specifying a name, date, and number of rounds.
    -   Admin can delete or update events as needed (e.g., change the date or round count).

6. Display Voting Results
    -   Admin can display voting results for:
        -   A specific round.
        -   The entire event (aggregate of all rounds).

7. Backup Database via CSV
    -   Admin can export the current state of the votes and songs to a CSV file.
    -   This can be done via a download button on the admin page, ensuring data can be backed up or shared.

8. Admin Authentication
    -   Admin login page is protected by a password.
    -   Passwords are stored as hashed values in the admin_users table for security.

## Admin Page Flow
1.  Login: The admin logs in using a username and password.
1.  Create Event: Admin creates a new event (one-round or multi-round).
1.  Manage Songs: Admin can:
1.  View/edit the song list.
1.  Assign songs to the current event.
1.  Control Voting: Admin can:
1.  Start or stop voting for a round.
1.  Mark played songs after each round.
1.  View Results: Admin can view the voting results for a specific round or an entire event.
1.  Backup Data: Admin can export the votes and songs data to CSV for backup purposes.