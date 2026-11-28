from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from kekspuh.db_functions import (
    NOT_FOUND_PREFIX,
    connect_db,
    delete_playlist_entries,
    delete_playlist_entries_by_uris,
    get_deduplicated_master_candidates,
    get_matched_recent_plays_for_playlists,
    get_overflow_playlist_entries,
    get_playlist_tracked_uris,
    get_recent_plays_for_matching,
    get_unmatched_tracks,
    init_db,
    is_not_found_uri,
    is_play_in_playlist,
    is_track_anywhere_in_playlist,
    is_track_recently_in_playlist,
    record_playlist_entry,
    save_spotify_match,
    save_spotify_not_found,
)
from kekspuh.spottuh import SpotifyClient, SpotifyCooldownError


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
        name="Early",
        playlist_id="3e8nuLQwxhd3JffqsIH5HB",
        max_tracks=200,
        program_name="Early",
    ),
    PlaylistRule(
        name="The Morning Show",
        playlist_id="0jLdBH7bUQntstL8lsaFcf",
        max_tracks=200,
        program_name="The Morning Show",
    ),
    PlaylistRule(
        name="The Midday Show",
        playlist_id="4RYM5nA6cEjEYz2mVZsJV3",
        max_tracks=200,
        program_name="The Midday Show",
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

MASTER_PLAYLIST_ID = "5N1q6gppmeMZxb7zhuiYhK"


def get_master_playlist_max_tracks(
    rules: tuple[PlaylistRule, ...] = PLAYLIST_RULES,
) -> int:
    """Dynamically sums max_tracks across all configured show/host rules."""
    return sum(rule.max_tracks for rule in rules)


def _trim_playlist_from_db(
    spotify: SpotifyClient,
    playlist_id: str,
    max_tracks: int,
) -> None:
    """
    Trims excess tracks from <playlist_id> using strictly local SQLite state
    (zero Spotify GET requests).
    """
    with connect_db() as conn:
        overflow = get_overflow_playlist_entries(conn, playlist_id, max_tracks)

    if not overflow:
        return

    overflow_play_ids = [pid for pid, _ in overflow]
    overflow_uris = [uri for _, uri in overflow]

    spotify.remove_tracks_from_playlist(playlist_id, overflow_uris)

    with connect_db() as conn:
        delete_playlist_entries(conn, playlist_id, overflow_play_ids)


def sync_recent_playlists(
    recent_limit: int = 1,
    rules: tuple[PlaylistRule, ...] = PLAYLIST_RULES,
) -> int:
    if not rules:
        return 0

    additions_made = 0

    with connect_db() as conn:
        recent_plays = get_recent_plays_for_matching(conn, limit=recent_limit)

    if not recent_plays:
        return 0

    session_uri_cache: dict[int, str] = {}

    with SpotifyClient() as spotify:
        if spotify.quota.get_cooldown_remaining() > 0:
            mins = float(spotify.quota.get_cooldown_remaining() / 60)
            print(
                f"[Spotify] Cooldown active ({mins:.1f} min remaining). Skipping sync."
            )
            return 0

        try:
            for play in recent_plays:
                play_id: int = play["play_id"]
                track_ref: int = play["track_ref"]
                track_name: str = play["track_name"]
                artist_name: str = play["artist_name"]

                cached_uri: str | None = play[
                    "spotify_track_uri"
                ] or session_uri_cache.get(track_ref)

                if is_not_found_uri(cached_uri):
                    continue

                if cached_uri is None:
                    match = spotify.search_track(track_name, artist_name)
                    if not match:
                        print(
                            f"[Matcher] No Spotify match (marked NOT FOUND): "
                            f"'{track_name}' by '{artist_name}'"
                        )
                        session_uri_cache[track_ref] = f"{NOT_FOUND_PREFIX}{track_ref}"
                        with connect_db() as conn:
                            save_spotify_not_found(conn, track_ref)
                        time.sleep(0.5)
                        continue

                    track_uri: str = match.track_uri
                    session_uri_cache[track_ref] = track_uri

                    with connect_db() as conn:
                        save_spotify_match(
                            conn,
                            track_ref=track_ref,
                            track_uri=match.track_uri,
                            track_name=match.track_name,
                            match_tier=match.match_tier,
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
                else:
                    track_uri = cached_uri

                if is_not_found_uri(track_uri):
                    continue

                for rule in rules:
                    if not rule.matches(play):
                        continue

                    with connect_db() as conn:
                        already_added = is_play_in_playlist(
                            conn, rule.playlist_id, play_id
                        )
                        recently_spun = (
                            False
                            if already_added
                            else is_track_recently_in_playlist(
                                conn, rule.playlist_id, track_uri, recent_window=20
                            )
                        )

                    if already_added or recently_spun:
                        continue

                    spotify.add_tracks_to_playlist(
                        playlist_id=rule.playlist_id,
                        track_uris=[track_uri],
                        position=0,
                    )

                    with connect_db() as conn:
                        record_playlist_entry(
                            conn, rule.playlist_id, play_id, track_uri
                        )

                    _trim_playlist_from_db(spotify, rule.playlist_id, rule.max_tracks)

                    additions_made += 1
                    print(
                        f"[Playlist: {rule.name}] Added '{track_name}' (play_id={play_id})"
                    )
        except SpotifyCooldownError as err:
            print(f"[Spotify] {err}")
        finally:
            spotify.print_quota_summary()

    return additions_made


def sync_master_playlist(
    master_playlist_id: str = MASTER_PLAYLIST_ID,
    rules: tuple[PlaylistRule, ...] = PLAYLIST_RULES,
) -> tuple[int, int]:
    """
    Runs around midnight (or manually via Option 5):
      1. Computes max_tracks = sum(rule.max_tracks for rule in rules).
      2. Queries SQLite for up to <max_tracks> already-deduplicated track URIs
         across all configured show/host playlists.
      3. Diffs against what is currently in <master_playlist_id> in playlist_entry:
         - Batch-removes stale URIs (up to 100/request).
         - Batch-adds new URIs (up to 100/request).
      Returns (added_count, removed_count).
    """
    if not rules or not master_playlist_id:
        print(
            "[Master Playlist] MASTER_PLAYLIST_ID is not configured in spot_match.py."
        )
        return 0, 0

    target_max = get_master_playlist_max_tracks(rules)
    source_ids = tuple(rule.playlist_id for rule in rules)

    with connect_db() as conn:
        planned = get_deduplicated_master_candidates(
            conn, source_playlist_ids=source_ids, limit=target_max
        )
        current_uris = get_playlist_tracked_uris(conn, master_playlist_id)

    planned_by_uri = {row["spotify_track_uri"]: row["play_id"] for row in planned}
    planned_uris = set(planned_by_uri.keys())

    uris_to_add = [
        row["spotify_track_uri"]
        for row in planned
        if row["spotify_track_uri"] not in current_uris
    ]
    uris_to_remove = [uri for uri in current_uris if uri not in planned_uris]

    if not uris_to_add and not uris_to_remove:
        print(
            f"[Master Playlist] Already up to date ({len(current_uris)}/{target_max} unique tracks)."
        )
        return 0, 0

    with SpotifyClient() as spotify:
        if spotify.quota.get_cooldown_remaining() > 0:
            mins = float(spotify.quota.get_cooldown_remaining() / 60)
            print(
                f"[Master Playlist] Cooldown active ({mins:.1f} min remaining). Skipping sync."
            )
            return 0, 0

        try:
            if uris_to_remove:
                spotify.remove_tracks_from_playlist(master_playlist_id, uris_to_remove)
                with connect_db() as conn:
                    delete_playlist_entries_by_uris(
                        conn, master_playlist_id, uris_to_remove
                    )

            if uris_to_add:
                spotify.add_tracks_to_playlist(
                    master_playlist_id, uris_to_add, position=0
                )
                with connect_db() as conn:
                    for uri in uris_to_add:
                        record_playlist_entry(
                            conn, master_playlist_id, planned_by_uri[uri], uri
                        )
        except SpotifyCooldownError as err:
            print(f"[Master Playlist] {err}")
            return 0, 0
        finally:
            spotify.print_quota_summary()

    print(
        f"[Master Playlist] Synced ({len(planned_uris)}/{target_max} cap): "
        f"+{len(uris_to_add)} added, -{len(uris_to_remove)} removed."
    )
    return len(uris_to_add), len(uris_to_remove)


def sync_existing_matches_to_playlists(
    recent_limit: int = 200,
    rules: tuple[PlaylistRule, ...] = PLAYLIST_RULES,
) -> int:
    if not rules:
        return 0

    additions_made = 0

    with connect_db() as conn:
        matched_plays = get_matched_recent_plays_for_playlists(conn, limit=recent_limit)

    if not matched_plays:
        print("[Playlists] No matched recent plays found in database.")
        return 0

    pending_by_rule: dict[PlaylistRule, list[tuple[int, str]]] = {
        rule: [] for rule in rules
    }

    with connect_db() as conn:
        for play in matched_plays:
            play_id: int = play["play_id"]
            track_uri: str = play["spotify_track_uri"]
            if is_not_found_uri(track_uri):
                continue

            for rule in rules:
                if not rule.matches(play):
                    continue
                if is_track_anywhere_in_playlist(conn, rule.playlist_id, track_uri):
                    continue
                if any(uri == track_uri for _, uri in pending_by_rule[rule]):
                    continue
                pending_by_rule[rule].append((play_id, track_uri))

    with SpotifyClient() as spotify:
        try:
            for rule, items in pending_by_rule.items():
                if not items:
                    continue
                uris = [uri for _, uri in items]
                spotify.add_tracks_to_playlist(rule.playlist_id, uris, position=0)

                with connect_db() as conn:
                    for play_id, uri in items:
                        record_playlist_entry(conn, rule.playlist_id, play_id, uri)

                _trim_playlist_from_db(spotify, rule.playlist_id, rule.max_tracks)
                additions_made += len(items)
                print(f"[Playlist: {rule.name}] Batch-added {len(items)} track(s).")
        except SpotifyCooldownError as err:
            print(f"[Spotify] {err}")
        finally:
            spotify.print_quota_summary()

    return additions_made


def match_unmatched_tracks(
    batch_limit: int = 100,
    recheck_not_found: bool = False,
) -> int:
    matched_count = 0
    not_found_count = 0

    with connect_db() as conn:
        candidates = get_unmatched_tracks(
            conn, limit=batch_limit, include_not_found=recheck_not_found
        )

    if not candidates:
        print("[Matcher] No candidate tracks found to process.")
        return 0

    with SpotifyClient() as spotify:
        if spotify.quota.get_cooldown_remaining() > 0:
            mins = float(spotify.quota.get_cooldown_remaining() / 60)
            print(
                f"[Matcher] Cooldown active ({mins:.1f} min remaining). Aborting batch."
            )
            return 0

        try:
            for idx, item in enumerate(candidates, start=1):
                track_ref: int = item["track_ref"]
                track_name: str = item["track_name"]
                artist_name: str = item["artist_name"]

                match = spotify.search_track(track_name, artist_name)
                if not match:
                    not_found_count += 1
                    with connect_db() as conn:
                        save_spotify_not_found(conn, track_ref)
                    print(
                        f"[Matcher] ({idx}/{len(candidates)}) NOT FOUND: "
                        f"'{track_name}' by '{artist_name}'"
                    )
                    time.sleep(0.75)
                    continue

                with connect_db() as conn:
                    save_spotify_match(
                        conn,
                        track_ref=track_ref,
                        track_uri=match.track_uri,
                        track_name=match.track_name,
                        match_tier=match.match_tier,
                        artist_ref=item["artist_ref"],
                        artist_uri=match.artist_uri,
                        artist_name=match.artist_name,
                        album_ref=item["album_ref"],
                        album_uri=match.album_uri,
                        album_name=match.album_name,
                    )

                matched_count += 1
                print(
                    f"[Matcher] ({idx}/{len(candidates)}) MATCHED [Tier {match.match_tier}]: "
                    f"'{track_name}' -> {match.track_name} ({match.track_uri})"
                )
                time.sleep(0.75)
        except SpotifyCooldownError as err:
            print(f"[Matcher] {err}")
        finally:
            print(
                f"[Matcher] Batch summary: {matched_count} matched, "
                f"{not_found_count} marked NOT FOUND."
            )
            spotify.print_quota_summary()

    return matched_count


if __name__ == "__main__":
    init_db()
    added = sync_recent_playlists(recent_limit=1)
    print(f"\nDone. Added {added} track(s) across configured playlists.")
