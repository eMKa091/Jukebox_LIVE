# Thought map of currently coded solution + future

1. Use WebSockets or Polling for Real-Time Interactivity

To make the voting process more interactive and real-time, 
Streamlit has built-in support for polling, using the st_autorefresh() method. 
WebSockets can be used for real-time communication to instantly
push updates to the audience when voting rounds open/close. 
WebSockets can be integrated using third-party services like Pusher or PubNub.

2. More Secure Authentication for Admin Page

3. Dynamic Song List Management
In current concept, the song list appears static. 
If we want more flexibility, we must consider allowing the admin to:

-   Upload new song lists (CSV or even manually input songs) for each round.
-   Keep the song lists stored in the database, so you don't have to hardcode them or rely on static files.

4. Session and User ID Handling for More Reliable One-Time Voting
While Streamlit’s session state is helpful, session-based voting may not be fully reliable in all scenarios (e.g., users refreshing the browser or switching devices). To improve reliability, consider:

-   Requiring users to enter an email, phone number, or unique code (that you give at the concert) to vote,
    which will allow for stricter user tracking across devices.
-   Alternatively, implement basic device fingerprinting to track voting attempts across sessions.
    This can reduce the likelihood of users exploiting session state to vote multiple times.

5. Performance and Scaling Considerations
For larger concerts, if we expect hundreds of simultaneous users:

SQLite may not be sufficient for scaling. 
If performance becomes an issue, switching to a cloud database like PostgreSQL would be ideal. 
This ensures better concurrent access and can handle a larger number of requests.
We can migrate from SQLite to PostgreSQL fairly easily using SQLAlchemy or a similar ORM.

However, cloud = costs, not small ones.

6. Mobile-First UI Design
Assuming concert attendees will mostly use their smartphones, UI must be mobile-friendly:

