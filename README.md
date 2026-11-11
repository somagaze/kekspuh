## kekspuh

Personal project to learn Python. Motivation was from another spotify user who created
playlists based on KEXP 90.3 FM shows (e.g., Morning Show, Drive Time, Street Sounds).
Unfortunately, the playlist became unavailable in October 2026, so I figured it was time
to learn how to do it.

### Overview

*kekspuh* aims to build a system for fetching, storing, creating playlists, and
potentially generating trivia/facts from data retrieved from the KEXP.org API. I am
currently focused on the backend development, with the goal of ingesting data and storing
it in a SQLite database. Future plans include developing trivia generation and creating a
streaming website to display real-time results.

### Current Status

- **Backend**:
    - Implemented a Python-based ingestion engine that fetches data from several KEXP.org
      API
      endpoints: hosts, plays, programs, shows, and timeslots.

- **Database**:
    - The schema includes unique indexes to ensure data deduplication and performance.
    - Tables are structured to handle relationships between shows, DJs, artists, labels,
      albums,
      tracks, plays, and other endpoint metadata.
    - Holy crap, databases, foreign keys, indexes, junction tables... my mind is mush
      from trying to
      figure that out.

- **Data Handling Functions**:
    - Functions like `resolve_artist`, `resolve_label`, `resolve_album`, and
      `resolve_track` ensure that entities are correctly inserted and retrieved from the
      database.
    - I tried my best to de-duplicate everything but the individual `play`. Only took me
      forever. I'm a writer, not a programmer. Solving puzzles with python is re-wiring
      my brain, but it's fun to find solutions. My favorite was accounting for all the
      "Bob McKenzie feat. Doug" artist fingerprints so a track with the same artists will
      always be deduplicated by parsing and delimiting MusicBrainz artist fingerprints in
      alpha order.
    - The `save_batch` function handles batch insertion of play records and their
      associated metadata. My first attempt caused a 5GB database that took ~1min to
      perform one query... and that is when I learned about relational databases.

- **API Integration**:
    - The project integrates with the Spotify API to handle user authentication and
      playlist creation.
    - Functions like `get_valid_access_token` manage OAuth tokens for secure API access.
    - The `create_public_playlist_interactive` function allows users to create a public
      playlist on their Spotify account via the terminal.
    - My partner humored me when I ran across the house and told her, "I logged myself
      in to my own app!"

### REAL Current Status

- **No Idea if This Works**. I have refactored the "plays" endpoint ingestion and finally
  added the other endpoints; split modules into distinct functions, and pulled my hair
  out (what's left of it) figuring out the database (I needed to make mermaid flowcharts
  to understand it). Spotify playlist editing is working, but I have not tested the
  refactored ingestion code yet.

### UNREAL Current Status

- A old video game from 1998

### Next Steps

- ~~**Other Endpoints**:~~
    - ~~There are several other endpoints I would like to ingest that will greatly expand
      data for trivia, including v1 endpoints:~~
        - ~~[KEXP API](https://api.kexp.org/v2/)~~
        - ~~[Legacy API](https://api.kexp.org/v1/)~~
- **Trivia/Facts Generation**:
    - Develop algorithms to generate trivia questions or interesting facts based on the
      ingested data: "Troy Nelson plays <track> more often on Tuesdays that any other
      day; but if it is raining during his show, he typically plays <band's> cover of the
      song."
- **Streaming Website**:
    - Create a web interface to display real-time streaming results and trivia/facts. I
      will attempt to use my non-existent design skills... wish me luck
- **Testing and Optimization**:
    - Implement comprehensive testing to ensure data integrity and system reliability...
      heh, just kidding. I have no idea how to test yet.
    - Optimize database performance and API calls for efficiency, I WILL NEED TO LEARN
      THE SYNTAX TO YELL AT MY DATABASE AND FIGURE OUT WHERE MY INEFFICIENCIES ARE;
- **NEW! Spotify Matching**:
    - Get a Spotify matching function going to slog through millions of plays and match
      track, album, and artist Spotify URIs.
