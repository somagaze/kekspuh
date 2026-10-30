import json
import sqlite3
import time
from collections.abc import Iterator
from datetime import datetime
from typing import cast
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from kekspuh.db_functions import (
    connect_db,
    get_oldest_airdate,
    init_db,
    save_batch,
)
from kekspuh.models import JsonFromKexp, JsonResultsEnvelope, JsonResultsForDb


def main() -> None:
    init_db()

    pages_to_ingest = 2000
    page_size = 100

    with (
        httpx.Client() as http_client,
        connect_db() as db_conn,
    ):
        start_url = construct_backfill_url(db_conn, page_size)
        print(f"beginning backfill run from {start_url}")
        print(
            f"targeting up to {pages_to_ingest} pages ({pages_to_ingest * page_size} records)..."
        )

        total_saved = run_polling(
            client=http_client,
            conn=db_conn,
            start_url=start_url,
            max_pages=pages_to_ingest,
        )
        print(
            f"backfill completed, {total_saved} records committed to database."
        )


def construct_backfill_url(conn: sqlite3.Connection, limit: int = 100) -> str:
    base_endpoint = f"https://api.kexp.org/v2/plays/?limit={limit}"
    oldest_airdate = get_oldest_airdate(conn)

    if oldest_airdate:
        iso_timestamp = oldest_airdate.replace(" ", "T")
        if not iso_timestamp.endswith("Z"):
            iso_timestamp += "Z"

        encoded_timestamp = quote(iso_timestamp)
        return f"{base_endpoint}&airdate_before={encoded_timestamp}"
    return base_endpoint


def run_polling(
    client: httpx.Client,
    conn: sqlite3.Connection,
    start_url: str,
    max_pages: int,
) -> int:

    total_records_committed = 0

    for page_counter, all_results in enumerate(
        iterate_api_calls(client, start_url, max_pages), start=1
    ):
        db_entry_batch: list[JsonResultsForDb] = []

        for single_result in all_results:
            db_entry_record = build_results_package(single_result)
            if db_entry_record is not None:
                db_entry_batch.append(db_entry_record)

        if db_entry_batch:
            newly_inserted = save_batch(conn, db_entry_batch)
            total_records_committed += newly_inserted
            timenow = datetime.now(ZoneInfo("America/Los_Angeles")).strftime(
                "%H:%M:%S"
            )

            print(
                f"{timenow} [PAGE {page_counter:03d}] ingested {len(db_entry_batch)} plays "
                f"-> committed {newly_inserted:03d} new rows (run total: {total_records_committed})"
            )
    return total_records_committed


def iterate_api_calls(
    client: httpx.Client, start_url: str, max_pages: int
) -> Iterator[list[JsonResultsEnvelope]]:
    api_page_url: str | None = start_url
    api_pages_fetched = 0

    while api_page_url and api_pages_fetched < max_pages:
        resp = client.get(api_page_url, timeout=15.0)
        resp.raise_for_status()
        payload_all = cast(JsonFromKexp, resp.json())

        payload_results = payload_all.get("results") or []
        if payload_results:
            yield payload_results

        api_page_url = payload_all.get("next")
        api_pages_fetched += 1
        time.sleep(0.5)


def serialized_id_list(raw_list: object) -> str | None:
    if isinstance(raw_list, list) and raw_list:
        typed_list = cast(list[object], raw_list)
        clean_items: list[str] = [
            str(item).strip()
            for item in typed_list
            if item is not None and str(item).strip()
        ]
        return ",".join(clean_items) if clean_items else None
    return None


def build_results_package(
    songs_data: JsonResultsEnvelope,
) -> JsonResultsForDb | None:
    raw_id = songs_data.get("id")
    if not isinstance(raw_id, int):
        return None
    raw_results_json = json.dumps(songs_data)

    airdate = parse_iso_play_time(songs_data.get("airdate"))
    release_date = parse_release_date(songs_data.get("release_date"))

    artist_ids_delimited = serialized_id_list(songs_data.get("artist_ids"))
    labels_delimited = serialized_id_list(songs_data.get("labels"))
    label_ids_delimited = serialized_id_list(songs_data.get("label_ids"))

    return JsonResultsForDb(
        play_id=raw_id,
        play_uri=songs_data.get("uri"),
        airdate=airdate,
        show_id=songs_data.get("show"),
        show_uri=songs_data.get("show_uri"),
        image_uri=songs_data.get("image_uri"),
        thumbnail_uri=songs_data.get("thumbnail_uri"),
        track_name=songs_data.get("song"),
        track_brainz=songs_data.get("track_id"),
        recording_brainz=songs_data.get("recording_id"),
        artist_name=songs_data.get("artist"),
        artist_brainz=artist_ids_delimited,
        album_name=songs_data.get("album"),
        release_brainz=songs_data.get("release_id"),
        release_group_brainz=songs_data.get("release_group_id"),
        label=labels_delimited,
        label_brainz=label_ids_delimited,
        release_date=release_date,
        rotation_status=songs_data.get("rotation_status"),
        is_local=songs_data.get("is_local"),
        is_request=songs_data.get("is_request"),
        is_live=songs_data.get("is_live"),
        comment=songs_data.get("comment"),
        location=songs_data.get("location"),
        location_name=songs_data.get("location_name"),
        play_type=songs_data.get("play_type"),
        raw_json=raw_results_json,
    )


def parse_iso_play_time(raw_str: str | None) -> str | None:
    if not raw_str:
        return None
    try:
        cleaned_play_dt = datetime.fromisoformat(raw_str).astimezone()
        return cleaned_play_dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def parse_release_date(raw_str: str | None) -> str | None:
    if not raw_str:
        return None
    release_date_check = raw_str.strip()
    if len(release_date_check) == 4 and release_date_check.isdigit():
        return release_date_check
    try:
        cleansed_released_dt = datetime.fromisoformat(release_date_check)
        return cleansed_released_dt.strftime("%Y")
    except ValueError:
        return None


if __name__ == "__main__":
    main()
