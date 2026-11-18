from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime
from typing import Any

import httpx

from kekspuh.db_functions import (
    PACIFIC_TZ,
    connect_db,
    get_latest_timestamp,
    get_oldest_timestamp,
    init_db,
    save_batch,
    save_host,
    save_program,
    save_raw_payload,
    save_show,
    save_timeslot,
)
from kekspuh.endpoint_ingest import build_results_package
from kekspuh.endpoint_jobber import KexpClient
from kekspuh.spot_match import match_unmatched_tracks, sync_recent_playlists

ALL_ENDPOINTS: tuple[str, ...] = ("programs", "hosts", "shows", "timeslots", "plays")


def prompt_int(prompt: str, min_val: int, max_val: int) -> int:
    while True:
        try:
            val = int(input(f"{prompt} [{min_val}-{max_val}]: "))
            if min_val <= val <= max_val:
                return val
            print(f"Error: Value must be between {min_val} and {max_val}.")
        except ValueError:
            print("Error: Input must be a valid integer.")


def prompt_endpoint(endpoints: tuple[str, ...] = ALL_ENDPOINTS) -> str:
    print("\nAvailable Endpoints:")
    for idx, name in enumerate(endpoints, start=1):
        print(f"  [{idx}] {name}")
    choice = prompt_int("Select endpoint", 1, len(endpoints))
    return endpoints[choice - 1]


def confirm_action(warning_msg: str) -> bool:
    print(f"\n[WARNING] {warning_msg}")
    reply = input(
        'Type "YES" in all uppercase to proceed, or anything else to cancel: '
    )
    return reply == "YES"


def process_batch(conn: Any, endpoint: str, results: list[dict[str, Any]]) -> int:
    new_inserts = 0
    with conn:
        if endpoint == "plays":
            records = []
            for item in results:
                parsed = build_results_package(item)
                if parsed:
                    records.append(parsed)
            new_inserts = save_batch(conn, records)
        else:
            for item in results:
                entity_id = item.get("id")
                if isinstance(entity_id, int):
                    save_raw_payload(conn, endpoint, entity_id, json.dumps(item))

                if endpoint == "shows":
                    cur = conn.execute(
                        "SELECT 1 FROM show WHERE show_id = ? AND uri IS NOT NULL;",
                        (entity_id,),
                    )
                    already_complete = cur.fetchone() is not None
                    save_show(conn, item)
                    if not already_complete:
                        new_inserts += 1
                elif endpoint == "hosts":
                    save_host(conn, item)
                elif endpoint == "programs":
                    save_program(conn, item)
                elif endpoint == "timeslots":
                    save_timeslot(conn, item)
    return new_inserts


def run_backfill() -> None:
    print("\n--- Option 1: Backfill Historical Data ---")
    endpoint = prompt_endpoint()

    if endpoint == "plays":
        confirmed = confirm_action(
            "You've selected backfill <plays>\n"
            "To resolve foreign keys, ensure you have first backfilled:\n"
            "  1. <programs> & <hosts> THEN\n"
            "  2. <timeslots> & <shows>"
        )
        if not confirmed:
            print("Action cancelled.")
            return

    elif endpoint in ("shows", "timeslots"):
        confirmed = confirm_action(
            f"You've selected backfill <{endpoint}>\n"
            "To resolve foreign keys, ensure you have first backfilled:\n"
            "  <programs> & <hosts>"
        )
        if not confirmed:
            print("Action cancelled.")
            return

    page_size = prompt_int("Page size (limit)", 1, 100)
    max_pages = prompt_int("Max pages to backfill", 1, 1000)

    with connect_db() as conn:
        oldest_ts = get_oldest_timestamp(conn, endpoint)
        params: dict[str, Any] = {}

        if oldest_ts:
            if endpoint == "plays":
                params["airdate_before"] = oldest_ts
                print(f"Backfilling plays older than: {oldest_ts}")
            elif endpoint == "shows":
                params["start_time_before"] = oldest_ts
                print(f"Backfilling shows older than: {oldest_ts}")
        else:
            print(
                f"No existing <{endpoint}> records found in database."
                "Starting from the present."
            )

        client = KexpClient()
        total_items = 0

        for page_idx, page in enumerate(
            client.paginate_endpoint(
                endpoint, limit=page_size, max_pages=max_pages, params=params
            ),
            start=1,
        ):
            committed = process_batch(conn, endpoint, page)
            total_items += len(page)
            now_str = datetime.now(PACIFIC_TZ).strftime("%H:%M:%S")
            print(
                f"{now_str} [Page {page_idx:03d}] Ingested {len(page)} <{endpoint}> "
                f"-> committed {committed} rows (Total: {total_items})"
            )

    print(f"\n[Completed] Backfilled {total_items} items from <{endpoint}>.")


def _forward_fill_single_endpoint(
    conn: Any,
    client: KexpClient,
    endpoint: str,
    page_size: int = 50,
    max_pages: int = 500,
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
        print(
            f"{now_str} [{endpoint}] [Page {page_idx:02d}] Ingested {len(page)} items "
            f"-> committed {committed} new rows"
        )

        if committed == 0:
            print(f"[{endpoint}] Hit full pages of duplicate. Catch-up complete.")
            break

    return total_committed


def run_forward_fill(
    endpoints: tuple[str, ...] = ("shows", "plays"),
    page_size: int = 50,
    max_pages: int = 500,
    interactive: bool = True,
) -> dict[str, int]:
    if interactive:
        print("\n--- Option 2: Incremental Forward Fill (Shows + Plays) ---")

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
            )

    if interactive:
        summary = ", ".join(
            f"{ep}: +{count}" for ep, count in results_by_endpoint.items()
        )
        print(f"\n[Completed] Forward Fill Finished ({summary}).")
        new_plays = results_by_endpoint.get("plays", 0)
        if new_plays > 0:
            sync_recent_playlists(recent_limit=min(new_plays + 5, 200))

    return results_by_endpoint


def run_spotify_match_only(recheck_not_found: bool = False) -> None:
    label = (
        "Option 4: Recheck Spotify NOT FOUND Tracks (DB Only)"
        if recheck_not_found
        else "Option 3: Spotify Match Unmatched Tracks (DB Only)"
    )
    print(f"\n--- {label} ---")
    batch_size = prompt_int("How many tracks to process?", 1, 1000)
    matched = match_unmatched_tracks(
        batch_limit=batch_size, recheck_not_found=recheck_not_found
    )
    print(f"\n[Completed] Matched and saved {matched} track(s) to database.")


def run_periodic_polling() -> None:
    print("\n--- Option 3: Unattended Periodic Poller ---")
    print("Starting background poller:")
    print("  - <plays> polled every 60 seconds")
    print("  - <shows> Polled every 300 seconds (offset by 30 seconds)")
    print("Press Ctrl+C at any time to safely exit.")

    plays_interval = 60
    shows_interval = 300

    last_plays_poll = 0.0
    last_shows_poll = time.time() - shows_interval + 30.0

    try:
        while True:
            current_time = time.time()

            if current_time - last_shows_poll >= shows_interval:
                now_str = datetime.now(PACIFIC_TZ).strftime("%H:%M:%S")
                print(f"\n{now_str} [Poller] Checking for updated shows...")
                try:
                    run_forward_fill(
                        endpoints=("shows",),
                        page_size=20,
                        max_pages=50,
                        interactive=False,
                    )
                except (
                    httpx.HTTPError,
                    sqlite3.OperationalError,
                    OSError,
                    RuntimeError,
                ) as err:
                    print(f"Error polling shows: {err}")
                last_shows_poll = time.time()

            if current_time - last_plays_poll >= plays_interval:
                now_str = datetime.now(PACIFIC_TZ).strftime("%H:%M:%S")
                print(f"\n{now_str} [Poller] Checking for new plays...")
                try:
                    counts = run_forward_fill(
                        endpoints=("plays",),
                        page_size=20,
                        max_pages=100,
                        interactive=False,
                    )
                    if counts.get("plays", 0) > 0:
                        sync_recent_playlists(recent_limit=20)
                except (
                    httpx.HTTPError,
                    sqlite3.OperationalError,
                    OSError,
                    RuntimeError,
                ) as err:
                    print(f"Error polling plays: {err}")
                last_plays_poll = time.time()
            time.sleep(1.0)

    except KeyboardInterrupt:
        print("\n\n[Poller] Shutting down gracefully. Safe to disconnect.")


def run_cli() -> None:
    init_db()

    while True:
        print("\n=======================================================")
        print("                   KEKSPUH INGESTION                   ")
        print("=======================================================")
        print("  [1] Start polling (live KEXP + Spotify playlists)")
        print("  [2] Forward fill (catch up KEXP + Spotify playlists)")
        print("  [3] Spotify match tracks (DB only, no playlist edits)")
        print("  [4] Out through the in door")
        print("=======================================================\n")

        choice = prompt_int("Select operation", 1, 4)

        if choice == 1:
            run_periodic_polling()
        elif choice == 2:
            run_forward_fill()
        elif choice == 3:
            run_spotify_match_only()
        elif choice == 4:
            print(
                "\nFarewell, my brave Hobbits. My work is now finished."
                "\nHere at last, on the shores of the sea "
                "comes the end of our Fellowship."
                "\nI will not say do not weep, for not all tears are an evil.\n"
            )
            break


if __name__ == "__main__":
    run_cli()
