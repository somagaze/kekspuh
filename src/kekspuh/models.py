from dataclasses import dataclass
from typing import TypedDict


class JsonResultsEnvelope(TypedDict, total=False):
    play_id: int | None
    play_uri: str | None
    airdate: str | None
    show_id: int | None
    show_uri: str | None
    image_uri: str | None
    thumbnail_uri: str | None
    track_name: str | None
    track_brainz: str | None
    recording_brainz: str | None
    artist_name: str | None
    artist_id: list[str] | None
    album_name: str | None
    release_brainz: str | None
    release_group_brainz: str | None
    labels: str | None
    label_ids: list[str] | None
    release_date: str | None
    rotation_status: str | None
    is_local: str | None
    is_request: str | None
    is_live: str | None
    comment: str | None
    location: str | None
    location_name: str | None
    play_type: str | None


class JsonFromKexp(TypedDict, total=False):
    next: str | None
    previous: str | None
    results: list[JsonResultsEnvelope]


@dataclass(frozen=True)
class JsonResultsForDb:
    play_id: int | None
    play_uri: str | None
    airdate: str | None
    show_id: int | None
    show_uri: str | None
    image_uri: str | None
    thumbnail_uri: str | None
    track_name: str | None
    track_brainz: str | None
    recording_brainz: str | None
    artist_name: str | None
    artist_id: list[str] | None
    album_name: str | None
    release_brainz: str | None
    release_group_brainz: str | None
    labels: str | None
    label_ids: list[str] | None
    release_date: str | None
    rotation_status: str | None
    is_local: str | None
    is_request: str | None
    is_live: str | None
    comment: str | None
    location: str | None
    location_name: str | None
    play_type: str | None
    json_results_raw: str | None
