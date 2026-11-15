from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from kekspuh.db_functions import (
    connect_db,
    get_recent_plays_for_matching,
    init_db,
    is_play_in_playlist,
    record_playlist_entry,
    save_spotify_match,
)
from kekspuh.spottuh import SpotifyClient


@dataclass(frozen=True)
class PlaylistRule:
    name: str
    playlist_id: str
    max_tracks: int = 200
    program_name: str | None = None
    host_name: str | None = None

    def matches(self, play: dict[str, Any]) -> bool:
        if self.program_name is not None:
            play_program = (play.get("program_name") or "").strip().lower()
            if play_program != self.program_name.strip().lower():
                return False

        if self.host_name is not None:
            target_host = self.host_name.strip().lower()
            play_hosts = [h.strip().lower() for h in play.get("host_names", [])]
            if target_host not in play_hosts:
                return False

        return True


PLAYLIST_RULES: tuple[PlaylistRule, ...] = (
    PlaylistRule(
        name="KEXP Rolling",
        playlist_id="5N1q6gppmeMZxb7zhuiYhK",
        max_tracks=200,
    ),
    PlaylistRule(
        name="The Morning Show",
        playlist_id="0jLdBH7bUQntstL8lsaFcf",
        max_tracks=200,
        program_name="The Morning Show",
    ),
    PlaylistRule(
        name="The Afternoon Show",
        playlist_id="51IUW5EhqmgJFFzqZEfVs4",
        max_tracks=200,
        program_name="The Afternoon Show",
    ),
    PlaylistRule(
        name="Drive Time",
        playlist_id="10UrjcfxrXXUia5W5Ddp6q",
        max_tracks=200,
        program_name="Drive Time",
    ),
    PlaylistRule(
        name="Troy Nelson",
        playlist_id="4PrWdJkSfby81EM0JpJzlN",
        max_tracks=200,
        host_name="Troy Nelson",
    ),
)


def sync_recent_playlists(
    recent_limit: int = 20,
    rules: tuple[PlaylistRule, ...] = PLAYLIST_RULES,
) -> int:
    if not rules:
        return 0

    spotify = SpotifyClient()
    additions_made = 0

    with connect_db() as conn:
        recent_plays = get_recent_plays_for_matching(conn, limit=recent_limit)

    if not recent_plays:
        return 0

    session_uri_cache: dict[int, str] = {}

    for play in recent_plays:
        play_id: int = play["play_id"]
        track_ref: int = play["track_ref"]
        track_name: str = play["track_name"]
        artist_name: str = play["artist_name"]

        track_uri: str | None = play["spotify_track_uri"] or session_uri_cache.get(
            track_ref
        )

        if not track_uri:
            match = spotify.search_track(track_name, artist_name)
            if not match:
                print(f"[Matcher] No Spotify match: '{track_name}' by '{artist_name}'")
                continue

            track_uri: str = match.track_uri
            session_uri_cache[track_ref] = track_uri

            with connect_db() as conn:
                save_spotify_match(
                    conn,
                    track_ref=track_ref,
                    track_uri=match.track_uri,
                    track_name=match.track_name,
                    artist_ref=play["artist_ref"],
                    artist_uri=match.artist_uri,
                    artist_name=match.artist_name,
                    album_ref=play["album_ref"],
                    album_uri=match.album_uri,
                    album_name=match.album_name,
                )
            print(
                f"[Matcher] Matched '{track_name}' -> {match.track_name} ({track_uri})"
            )
            time.sleep(0.5)

        for rule in rules:
            if not rule.matches(play):
                continue

            with connect_db() as conn:
                already_added = is_play_in_playlist(conn, rule.playlist_id, play_id)

            if already_added:
                continue

            spotify.add_track_to_top(
                playlist_id=rule.playlist_id,
                track_uri=track_uri,
                max_limit=rule.max_tracks,
            )

            with connect_db() as conn:
                record_playlist_entry(conn, rule.playlist_id, play_id, track_uri)

            additions_made += 1
            print(f"[Playlist: {rule.name}] Added '{track_name}' (play_id={play_id})")

    return additions_made


if __name__ == "__main__":
    init_db()
    added = sync_recent_playlists(recent_limit=20)
    print(f"\nDone. Added {added} track(s) across configured playlists.")
