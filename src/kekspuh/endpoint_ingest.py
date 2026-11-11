from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from kekspuh.db_functions import parse_iso_to_utc
from kekspuh.models import JsonResultsEnvelope, JsonResultsForDb


def build_results_package(
    plays_results: JsonResultsEnvelope | dict[str, Any],
) -> JsonResultsForDb | None:
    id_key = plays_results.get("id")
    if not isinstance(id_key, int):
        return None

    results_dump = json.dumps(plays_results)

    parsed_air_dt = parse_iso_to_utc(plays_results.get("airdate"))
    parsed_rel_dt = parse_release_date(plays_results.get("release_date"))

    artist_id_delim = serialized_id_list(plays_results.get("artist_ids"))
    labels_delim = serialized_id_list(plays_results.get("labels"))
    label_id_delim = serialized_id_list(plays_results.get("label_ids"))

    is_local = str(plays_results.get("is_local", False)).lower()
    is_request = str(plays_results.get("is_request", False)).lower()
    is_live = str(plays_results.get("is_live", False)).lower()

    return JsonResultsForDb(
        play_id=id_key,
        play_uri=plays_results.get("uri"),
        airdate=parsed_air_dt,
        show_id=plays_results.get("show"),
        show_uri=plays_results.get("show_uri"),
        image_uri=plays_results.get("image_uri"),
        thumbnail_uri=plays_results.get("thumbnail_uri"),
        track_name=plays_results.get("song"),
        track_brainz=plays_results.get("track_id"),
        recording_brainz=plays_results.get("recording_id"),
        artist_name=plays_results.get("artist"),
        artist_brainz=artist_id_delim,
        album_name=plays_results.get("album"),
        release_brainz=plays_results.get("release_id"),
        release_group_brainz=plays_results.get("release_group_id"),
        label_name=labels_delim,
        label_brainz=label_id_delim,
        release_date=parsed_rel_dt,
        rotation_status=plays_results.get("rotation_status"),
        is_local=is_local,
        is_request=is_request,
        is_live=is_live,
        comment=plays_results.get("comment"),
        location=plays_results.get("location"),
        location_name=plays_results.get("location_name"),
        play_type=plays_results.get("play_type"),
        raw_json=results_dump,
    )


def parse_release_date(raw_str: str | None) -> str | None:
    if not raw_str:
        return None
    cleaned = raw_str.strip()
    if len(cleaned) == 4 and cleaned.isdigit():
        return cleaned
    try:
        dt = datetime.fromisoformat(cleaned)
        return dt.strftime("%Y")
    except ValueError:
        return None


def serialized_id_list(raw_list: list[str] | None) -> str | None:
    if not raw_list:
        return None
    clean_items = sorted({item.strip() for item in raw_list if item and item.strip()})
    return ",".join(clean_items) if clean_items else None
