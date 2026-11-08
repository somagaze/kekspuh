from kekspuh.spottuh import SpotifyClient

PLAYLIST_ID = "5N1q6gppmeMZxb7zhuiYhK"

track_name = str(input("Track Name: "))
artist_name = str(input("Artist Name: "))

spotify = SpotifyClient()
match = spotify.search_track(track_name, artist_name)
if match:
    spotify.add_track_to_top(PLAYLIST_ID, match.track_uri)
