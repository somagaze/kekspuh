from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict


class JsonFromKexp(TypedDict, total=False):
    """Raw JSON key-value pairs from API response.

    All fields are optional (total=False) to accommodate sparse or malformed
    upstream API responses.
    """

    next: str | None
    """Canonical URI for the next play payload."""

    previous: str | None
    """Canonical URI for the previous play payload."""

    """Substantive results for preparation for database ingestion."""
    results: list[JsonResultsEnvelope]


class JsonResultsEnvelope(TypedDict, total=False):
    """Raw JSON key-value pairs formatted for database ingestion.

    All fields are optional (total=False) to accommodate sparse or malformed
    upstream API responses.
    """

    id: int | None
    """Primary key for the play record."""

    uri: str | None
    """Canonical URI for the current play payload."""

    airdate: str | None
    """ISO 8601 timestamp denoting when the track or airbreak aired."""

    show: int | None
    """Foreign key referencing the parent KEXP show (V2 API)."""

    show_uri: str | None
    """Canonical URI for the full show payload (V2 API)."""

    image_uri: str | None
    """High-resolution album art or track image URI."""

    thumbnail_uri: str | None
    """Scaled thumbnail URI for track artwork."""

    song: str | None
    """Title of the aired track."""

    track_id: str | None
    """MusicBrainz Track MBID pointing to a specific release's track position."""

    recording_id: str | None
    """MusicBrainz Recording MBID identifying unique audio performance/mix."""

    artist: str | None
    """Credited artist string, including collaboration markers (e.g., 'A feat. B')."""

    artist_ids: list[str] | None
    """MusicBrainz Artist MBIDs corresponding to credited performers."""

    album: str | None
    """Title of the release or compilation containing the track."""

    release_id: str | None
    """MusicBrainz Release MBID for the specific physical or digital edition."""

    release_group_id: str | None
    """MusicBrainz Release Group MBID aggregating all editions of the release."""

    labels: list[str] | None
    """Names of record labels credited on the release."""

    label_ids: list[str] | None
    """MusicBrainz Label MBIDs associated with the release."""

    release_date: str | None
    """Release date string of the album or single (YYYY or YYYY-MM-DD)."""

    rotation_status: str | None
    """Station programming rotation tier assigned at airdate (e.g., Heavy, Medium)."""

    is_local: bool | None
    """Indicates Pacific Northwest or Northern California regional artist status."""

    is_request: bool | None
    """Indicates whether the spin fulfilled a listener request."""

    is_live: bool | None
    """Indicates an in-studio live performance rather than a commercial live cut."""

    comment: str | None
    """DJ or host annotations specific to the airplay event."""

    location: str | None
    """Broadcast origin market code (e.g., Seattle or Bay Area)."""

    location_name: str | None
    """Human-readable facility or studio name."""

    play_type: str | None
    """Event classification discriminator (e.g., 'trackplay', 'airbreak')."""


@dataclass(frozen=True)
class JsonResultsForDb:
    """Raw JSON key-value pairs prepared for database ingestion.

    All fields are optional (total=False) to accommodate sparse or malformed
    upstream API responses.
    """

    play_id: int | None
    """Primary key for the play record."""

    play_uri: str | None
    """Canonical URI for the current play payload."""

    """Parsed ISO 8601 timestamp denoting when the track or airbreak aired."""
    airdate: str | None

    """Foreign key referencing the parent KEXP show (V2 API)."""
    show_id: int | None

    """Canonical URI for the full show payload (V2 API)."""
    show_uri: str | None

    """High-resolution album art or track image URI."""
    image_uri: str | None

    """Scaled thumbnail URI for track artwork."""
    thumbnail_uri: str | None

    """Title of the aired track."""
    track_name: str | None

    """MusicBrainz Track MBID pointing to a specific release's track position."""
    track_brainz: str | None

    """MusicBrainz Recording MBID identifying unique audio performance/mix."""
    recording_brainz: str | None

    """Credited artist string, including collaboration markers (e.g., 'A feat. B')."""
    artist_name: str | None

    """Serialized and delimited MusicBrainz Artist MBIDs
    corresponding to credited performers."""
    artist_brainz: str | None

    """Title of the release or compilation containing the track."""
    album_name: str | None

    """MusicBrainz Release MBID for the specific physical or digital edition."""
    release_brainz: str | None

    """MusicBrainz Release Group MBID aggregating all editions of the release."""
    release_group_brainz: str | None

    """Serialized and delimited names of record labels credited on the release."""
    label_name: str | None

    """Serialized and delimited MusicBrainz Label MBIDs
    associated with the release."""
    label_brainz: str | None

    """Parsed release date string of the album or single (YYYY)."""
    release_date: str | None

    """Station programming rotation tier assigned at airdate (e.g., Heavy, Medium)."""
    rotation_status: str | None

    """Indicates Pacific Northwest or Northern California regional artist status."""
    is_local: str | None

    """Indicates whether the spin fulfilled a listener request."""
    is_request: str | None

    """Indicates an in-studio live performance rather than a commercial live cut."""
    is_live: str | None

    """DJ or host annotations specific to the airplay event."""
    comment: str | None

    """Broadcast origin market code (e.g., Seattle or Bay Area)."""
    location: str | None

    """Human-readable facility or studio name."""
    location_name: str | None

    """Event classification discriminator (e.g., 'trackplay', 'airbreak')."""
    play_type: str | None

    """Class list[JsonResultsEnvelope] cast into a string"""
    raw_json: str | None
