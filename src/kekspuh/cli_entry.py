from __future__ import annotations

import sqlite3
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from kekspuh.db_functions import (
    connect_db,
    get_latest_timestamp,
    init_db,
    save_batch,
    save_host,
    save_program,
    save_show,
    save_timeslot,
)
from kekspuh.endpoint_ingest import build_results_package
from kekspuh.endpoint_jobber import KexpClient
from kekspuh.spot_match import (
    match_unmatched_tracks,
    sync_existing_matches_to_playlists,
    sync_recent_playlists,
)

PACIFIC_TZ = ZoneInfo("America/Los_Angeles")


def prompt_int(prompt_text: str, min_val: int, max_val: int) -> int:
    while True:
        raw = input(f"{prompt_text} [{min_val}-{max_val}]: ").strip()
        try:
            val = int(raw)
            if min_val <= val <= max_val:
                return val
            print(f"Error: Value must be between {min_val} and {max_val}.")
        except ValueError:
            print("Error: Input must be a valid integer.")


def process_batch(
    conn: sqlite3.Connection, endpoint: str, results: list[dict[str, Any]]
) -> int:
    if not results:
        return 0

    if endpoint == "plays":
        batch = []
        for item in results:
            pkg = build_results_package(item)
            if pkg is not None:
                batch.append(pkg)
        return save_batch(conn, batch) if batch else 0

    new_inserts = 0
    for item in results:
        entity_id = item.get("id")
        if not isinstance(entity_id, int):
            continue

        if endpoint == "hosts":
            cur = conn.execute(
                "SELECT 1 FROM host WHERE host_id = ? AND uri IS NOT NULL;",
                (entity_id,),
            )
            already_complete = cur.fetchone() is not None
            save_host(conn, item)
            if not already_complete:
                new_inserts += 1

        elif endpoint == "programs":
            cur = conn.execute(
                "SELECT 1 FROM program WHERE program_id = ? AND uri IS NOT NULL;",
                (entity_id,),
            )
            already_complete = cur.fetchone() is not None
            save_program(conn, item)
            if not already_complete:
                new_inserts += 1

        elif endpoint == "shows":
            cur = conn.execute(
                "SELECT 1 FROM show WHERE show_id = ? AND uri IS NOT NULL;",
                (entity_id,),
            )
            already_complete = cur.fetchone() is not None
            save_show(conn, item)
            if not already_complete:
                new_inserts += 1

        elif endpoint == "timeslots":
            cur = conn.execute(
                "SELECT 1 FROM timeslot WHERE timeslot_id = ?;",
                (entity_id,),
            )
            already_complete = cur.fetchone() is not None
            save_timeslot(conn, item)
            if not already_complete:
                new_inserts += 1

    return new_inserts


def _forward_fill_single_endpoint(
    conn: sqlite3.Connection,
    client: KexpClient,
    endpoint: str,
    page_size: int = 50,
    max_pages: int = 500,
    quiet_when_empty: bool = False,
) -> int:
    latest_ts = get_latest_timestamp(conn, endpoint)
    params: dict[str, Any] = {}

    if latest_ts:
        if endpoint == "plays":
            params["airdate_after"] = latest_ts
        elif endpoint == "shows":
            params["start_time_after"] = latest_ts

    total_committed = 0
    for page_idx, page in enumerate(
        client.paginate_endpoint(
            endpoint, limit=page_size, max_pages=max_pages, params=params
        ),
        start=1,
    ):
        committed = process_batch(conn, endpoint, page)
        total_committed += committed
        now_str = datetime.now(PACIFIC_TZ).strftime("%H:%M:%S")
        if committed > 0 or not quiet_when_empty:
            print(
                f"{now_str} [{endpoint}] [Page {page_idx:02d}] Ingested {len(page)} items "
                f"-> committed {committed} new rows"
            )

        if committed == 0:
            if not quiet_when_empty:
                print(f"[{endpoint}] Hit full page of duplicates. Catch-up complete.")
            break

    return total_committed


def run_forward_fill(
    endpoints: tuple[str, ...] = ("shows", "plays"),
    page_size: int = 50,
    max_pages: int = 500,
    quiet_when_empty: bool = False,
) -> dict[str, int]:
    results_by_endpoint: dict[str, int] = {}
    client = KexpClient()

    with connect_db() as conn:
        for ep in endpoints:
            results_by_endpoint[ep] = _forward_fill_single_endpoint(
                conn=conn,
                client=client,
                endpoint=ep,
                page_size=page_size,
                max_pages=max_pages,
                quiet_when_empty=quiet_when_empty,
            )

    return results_by_endpoint


def _run_polling_loop(sync_spotify: bool) -> None:
    """
    Shared polling engine for Option 1 (sync_spotify=True) and Option 2 (sync_spotify=False).
      - Initial catch-up: ingests all shows & plays from most recent DB timestamp.
      - If sync_spotify=True: matches ONLY the single most recent play & updates playlists.
      - Polls <plays> every 30s and <shows> every 300s; for each newly ingested play,
        matches & updates playlists if sync_spotify=True.
    """
    print("\n[Catch-up] Ingesting KEXP shows & plays from latest database watermark...")
    try:
        initial_counts = run_forward_fill(
            endpoints=("shows", "plays"), page_size=50, max_pages=500
        )
        print(
            f"[Catch-up] Complete (shows: +{initial_counts.get('shows', 0)}, "
            f"plays: +{initial_counts.get('plays', 0)})."
        )
    except (httpx.HTTPError, sqlite3.OperationalError, OSError) as err:
        print(f"[Catch-up] Error during initial KEXP catch-up: {err}")

    if sync_spotify:
        print(
            "\n[Startup Sync] Matching single most recent play & updating playlists..."
        )
        try:
            sync_recent_playlists(recent_limit=1)
        except (
            httpx.HTTPError,
            sqlite3.OperationalError,
            OSError,
            RuntimeError,
        ) as err:
            print(f"[Startup Sync] Spotify error: {err}")

    print("\nStarting live polling loop:")
    print("  - <plays> polled every 30 seconds")
    print("  - <shows> polled every 300 seconds (offset by 15 seconds)")
    if sync_spotify:
        print(
            "  - Newly ingested plays will be matched on Spotify & added to playlists"
        )
    else:
        print("  - KEXP database ingestion only (no Spotify API calls)")
    print("Press Ctrl+C at any time to safely exit.\n")

    plays_interval = 30
    shows_interval = 300

    last_plays_poll = time.time()
    last_shows_poll = time.time() - shows_interval + 15.0

    try:
        while True:
            current_time = time.time()

            if current_time - last_shows_poll >= shows_interval:
                now_str = datetime.now(PACIFIC_TZ).strftime("%H:%M:%S")
                print(f"{now_str} [Poller] Checking for updated shows...")
                try:
                    run_forward_fill(
                        endpoints=("shows",),
                        page_size=20,
                        max_pages=20,
                        quiet_when_empty=True,
                    )
                except (httpx.HTTPError, sqlite3.OperationalError, OSError) as err:
                    print(f"[Poller] Error polling shows: {err}")
                last_shows_poll = time.time()

            if current_time - last_plays_poll >= plays_interval:
                now_str = datetime.now(PACIFIC_TZ).strftime("%H:%M:%S")
                print(f"{now_str} [Poller] Checking for new plays...")
                try:
                    counts = run_forward_fill(
                        endpoints=("plays",),
                        page_size=20,
                        max_pages=20,
                        quiet_when_empty=True,
                    )
                    new_plays = counts.get("plays", 0)
                    if new_plays > 0 and sync_spotify:
                        print(
                            f"{now_str} [Poller] {new_plays} new play(s) ingested -> "
                            "matching & updating playlists..."
                        )
                        sync_recent_playlists(recent_limit=new_plays)
                except (
                    httpx.HTTPError,
                    sqlite3.OperationalError,
                    OSError,
                    RuntimeError,
                ) as err:
                    print(f"[Poller] Error during plays poll/sync: {err}")
                last_plays_poll = time.time()

            time.sleep(1.0)

    except KeyboardInterrupt:
        print("\n\n[Poller] Shutting down gracefully. Safe to disconnect.")


def run_option_1_poll_kexp_and_spotify() -> None:
    print("\n--- Option 1: Periodically Poll KEXP & Update Playlists ---")
    _run_polling_loop(sync_spotify=True)


def run_option_2_poll_kexp_only() -> None:
    print("\n--- Option 2: Periodically Poll KEXP Only (DB Only) ---")
    _run_polling_loop(sync_spotify=False)


def run_option_3_match_tracks() -> None:
    print("\n--- Option 3: Spotify Match Tracks (Most Recent 100 Unmatched) ---")
    matched = match_unmatched_tracks(batch_limit=100, recheck_not_found=False)
    print(f"\n[Completed] Matched and saved {matched} track(s) to database.")


def run_option_4_match_not_found() -> None:
    print("\n--- Option 4: Spotify Match 'NOT FOUND' Tracks (Most Recent 100) ---")
    matched = match_unmatched_tracks(batch_limit=100, recheck_not_found=True)
    print(f"\n[Completed] Recovered and saved {matched} track(s) to database.")


def run_option_5_update_playlists_from_existing_matches() -> None:
    print(
        "\n--- Option 5: Spotify Update Playlists (Existing Matches Only, No Search Calls) ---"
    )
    lookback = prompt_int(
        "How many recent plays to scan for existing matches?", 10, 500
    )
    added = sync_existing_matches_to_playlists(recent_limit=lookback)
    print(f"\n[Completed] Added {added} track(s) across configured playlists.")


def run_option_6_ingest_other_endpoints() -> None:
    print(
        "\n--- Option 6: Ingest Other KEXP Endpoints (hosts, programs, timeslots) ---"
    )
    print("  [1] All three (hosts -> programs -> timeslots)")
    print("  [2] hosts only")
    print("  [3] programs only")
    print("  [4] timeslots only")
    selection = prompt_int("Select endpoint(s) to ingest", 1, 4)

    endpoints_map: dict[int, tuple[str, ...]] = {
        1: ("hosts", "programs", "timeslots"),
        2: ("hosts",),
        3: ("programs",),
        4: ("timeslots",),
    }
    target_endpoints = endpoints_map[selection]
    client = KexpClient()

    with connect_db() as conn:
        for ep in target_endpoints:
            print(f"\n[Ingest] Fetching '{ep}'...")
            total_committed = 0
            for page_idx, page in enumerate(
                client.paginate_endpoint(ep, limit=100, max_pages=100),
                start=1,
            ):
                committed = process_batch(conn, ep, page)
                total_committed += committed
                now_str = datetime.now(PACIFIC_TZ).strftime("%H:%M:%S")
                print(
                    f"{now_str} [{ep}] [Page {page_idx:02d}] Ingested {len(page)} items "
                    f"-> committed {committed} new rows"
                )
            print(f"[Ingest] Finished '{ep}' (total new rows: {total_committed}).")

    print("\n[Completed] KEXP reference endpoint ingestion finished.")


def run_cli() -> None:
    init_db()

    while True:
        print("\n================================================================")
        print("                       KEKSPUH  INGESTION                       ")
        print("================================================================")
        print("  [1] Periodically poll KEXP & update playlists")
        print("  [2] Periodically poll KEXP only (DB only)")
        print("  [3] Spotify match tracks (most recent 100 unmatched)")
        print("  [4] Spotify match 'NOT FOUND' tracks (most recent 100)")
        print("  [5] Spotify update playlists (existing DB matches only)")
        print("  [6] Ingest other KEXP endpoints (hosts, programs, timeslots)")
        print("  [7] Out through the in door")
        print("================================================================\n")

        choice = prompt_int("Select operation", 1, 7)

        if choice == 1:
            run_option_1_poll_kexp_and_spotify()
        elif choice == 2:
            run_option_2_poll_kexp_only()
        elif choice == 3:
            run_option_3_match_tracks()
        elif choice == 4:
            run_option_4_match_not_found()
        elif choice == 5:
            run_option_5_update_playlists_from_existing_matches()
        elif choice == 6:
            run_option_6_ingest_other_endpoints()
        elif choice == 7:
            print(
                "\nFarewell, my brave Hobbits. My work is now finished."
                "\nHere at last, on the shores of the sea "
                "comes the end of our Fellowship."
                "\nI will not say do not weep, for not all tears are an evil.\n"
            )
            break


if __name__ == "__main__":
    run_cli()
