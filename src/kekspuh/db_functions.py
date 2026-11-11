from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from kekspuh.models import JsonResultsForDb

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "kekspuh.sqlite3"
PACIFIC_TZ = ZoneInfo("America/Los_Angeles")


def connect_db(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA cache_size=-64000;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect_db(db_path) as conn:
        conn.executescript(
            """

            -- MOSTLY (HARMLESS) STATIC METADATA --

            CREATE TABLE IF NOT EXISTS host (
                host_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                image_uri TEXT,
                thumbnail_uri TEXT,
                is_active INTEGER DEFAULT 1,
                location INTEGER,
                uri TEXT
            );

            CREATE TABLE IF NOT EXISTS program (
                program_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                tags TEXT,
                image_uri TEXT,
                thumbnail_uri TEXT,
                is_active INTEGER DEFAULT 1,
                location INTEGER,
                location_name TEXT,
                uri TEXT
            );

            CREATE TABLE IF NOT EXISTS show (
                show_id INTEGER PRIMARY KEY,
                program_id INTEGER,
                start_time TEXT NOT NULL,
                tagline TEXT,
                image_uri TEXT,
                program_image_uri TEXT,
                location INTEGER,
                location_name TEXT,
                uri TEXT,
                FOREIGN KEY (program_id) REFERENCES program(program_id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS show_jx_host (
                show_id INTEGER NOT NULL,
                host_id INTEGER NOT NULL,
                PRIMARY KEY (show_id, host_id),
                FOREIGN KEY (show_id) REFERENCES show(show_id) ON DELETE CASCADE,
                FOREIGN KEY (host_id) REFERENCES host(host_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS timeslot (
                timeslot_id INTEGER PRIMARY KEY,
                program_id INTEGER NOT NULL,
                weekday INTEGER NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                duration TEXT,
                uri TEXT,
                FOREIGN KEY (program_id) REFERENCES program(program_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS timeslot_jx_host (
                timeslot_id INTEGER NOT NULL,
                host_id INTEGER NOT NULL,
                PRIMARY KEY (timeslot_id, host_id),
                FOREIGN KEY (timeslot_id) REFERENCES timeslot(timeslot_id) ON DELETE CASCADE,
                FOREIGN KEY (host_id) REFERENCES host(host_id) ON DELETE CASCADE
            );

            -- CRITICAL METADATA --

            CREATE TABLE IF NOT EXISTS artist (
                artist_ref INTEGER PRIMARY KEY AUTOINCREMENT,
                artist_name TEXT NOT NULL,
                artist_brainz TEXT,
                is_local INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS label (
                label_ref INTEGER PRIMARY KEY AUTOINCREMENT,
                label_name TEXT NOT NULL,
                label_brainz TEXT
            );

            CREATE TABLE IF NOT EXISTS album (
                album_ref INTEGER PRIMARY KEY AUTOINCREMENT,
                album_name TEXT NOT NULL,
                release_brainz TEXT,
                release_group_brainz TEXT,
                artist_ref INTEGER NOT NULL,
                label_ref INTEGER,
                FOREIGN KEY (artist_ref) REFERENCES artist(artist_ref) ON DELETE RESTRICT,
                FOREIGN KEY (label_ref) REFERENCES label(label_ref) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS track (
                track_ref INTEGER PRIMARY KEY AUTOINCREMENT,
                track_name TEXT NOT NULL,
                track_brainz TEXT,
                recording_brainz TEXT,
                release_date TEXT,
                artist_ref INTEGER NOT NULL,
                album_ref INTEGER,
                FOREIGN KEY (artist_ref) REFERENCES artist(artist_ref) ON DELETE RESTRICT,
                FOREIGN KEY (album_ref) REFERENCES album(album_ref) ON DELETE SET NULL
            );

            -- TRACKPLAY ENDPOINT: THE PURPOSE OF THE DATABASE --

            CREATE TABLE IF NOT EXISTS play (
                play_id INTEGER PRIMARY KEY,
                airdate TEXT NOT NULL,
                show_id INTEGER,
                play_type TEXT,
                track_ref INTEGER,
                is_request INTEGER DEFAULT 0,
                is_live INTEGER DEFAULT 0,
                rotation_status TEXT,
                comment TEXT,
                location INTEGER,
                location_name TEXT,
                image_uri TEXT,
                thumbnail_uri TEXT,
                play_uri TEXT,
                show_uri TEXT,
                FOREIGN KEY (show_id) REFERENCES show(show_id) ON DELETE SET NULL,
                FOREIGN KEY (track_ref) REFERENCES track(track_ref) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS raw_endpoint_json (
                endpoint_name TEXT NOT NULL,
                entity_id INTEGER NOT NULL,
                raw_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (endpoint_name, entity_id)
            );

            -- SPOTIFY MATCHING --

            CREATE TABLE IF NOT EXISTS spotify_track (
                track_ref INTEGER PRIMARY KEY,
                spotify_track_uri TEXT NOT NULL UNIQUE,
                spotify_track_name TEXT,
                matched_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (track_ref) REFERENCES track(track_ref) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS spotify_album (
                album_ref INTEGER PRIMARY KEY,
                spotify_album_uri TEXT NOT NULL UNIQUE,
                spotify_album_name TEXT,
                matched_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (album_ref) REFERENCES album(album_ref) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS spotify_artist (
                artist_ref INTEGER PRIMARY KEY,
                spotify_artist_uri TEXT NOT NULL UNIQUE,
                spotify_artist_name TEXT,
                matched_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (artist_ref) REFERENCES artist(artist_ref) ON DELETE CASCADE
            );

            -- DEDUPE --

            CREATE UNIQUE INDEX IF NOT EXISTS idx_artist_brainz
                ON artist(artist_brainz) WHERE artist_brainz IS NOT NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS idx_artist_name_fallback
                ON artist(artist_name) WHERE artist_brainz IS NULL;

            CREATE UNIQUE INDEX IF NOT EXISTS idx_label_brainz
                ON label(label_brainz) WHERE label_brainz IS NOT NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS idx_label_name_fallback
                ON label(label_name) WHERE label_brainz IS NULL;

            CREATE UNIQUE INDEX IF NOT EXISTS idx_album_brainz
                ON album(release_brainz) WHERE release_brainz IS NOT NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS idx_album_composite_fallback
                ON album(album_name, artist_ref) WHERE release_brainz IS NULL;

            CREATE UNIQUE INDEX IF NOT EXISTS idx_track_recording_brainz
                ON track(recording_brainz) WHERE recording_brainz IS NOT NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS idx_track_composite_fallback
                ON track(track_name, artist_ref, IFNULL(album_ref, -1)) WHERE recording_brainz IS NULL;

            -- PERFORMANCE --

            CREATE INDEX IF NOT EXISTS idx_play_airdate ON play(airdate);
            CREATE INDEX IF NOT EXISTS idx_play_show_id ON play(show_id);
            CREATE INDEX IF NOT EXISTS idx_play_track_ref ON play(track_ref);
            CREATE INDEX IF NOT EXISTS idx_show_program_id ON show(program_id);
            CREATE INDEX IF NOT EXISTS idx_show_start_time ON show(start_time);
            """  # noqa: E501
        )


def parse_iso_to_utc(raw_str: str | None) -> str | None:
    if not raw_str:
        return None
    try:
        dt = datetime.fromisoformat(raw_str)
        utc_dt = dt.astimezone(UTC)
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def to_pacific_time(utc_iso_str: str) -> datetime:
    clean_str = utc_iso_str.replace("Z", "+00:00")
    utc_dt = datetime.fromisoformat(clean_str)
    return utc_dt.astimezone(PACIFIC_TZ)


def save_raw_payload(
    conn: sqlite3.Connection, endpoint_name: str, entity_id: int, raw_json: str
) -> None:
    conn.execute(
        """
        INSERT INTO raw_endpoint_json (endpoint_name, entity_id, raw_json)
        VALUES (?, ?, ?)
        ON CONFLICT(endpoint_name, entity_id) DO UPDATE SET
            raw_json = excluded.raw_json,
            fetched_at = datetime('now');
        """,
        (endpoint_name, entity_id, raw_json),
    )


def save_host(conn: sqlite3.Connection, host_data: dict[str, Any]) -> None:
    host_id = host_data.get("id")
    if not isinstance(host_id, int):
        return

    conn.execute(
        """
        INSERT INTO host (host_id, name, image_uri, thumbnail_uri, is_active, location, uri)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(host_id) DO UPDATE SET
            name = excluded.name,
            image_uri = excluded.image_uri,
            thumbnail_uri = excluded.thumbnail_uri,
            is_active = excluded.is_active,
            location = excluded.location,
            uri = excluded.uri;
        """,  # noqa: E501
        (
            host_id,
            host_data.get("name", ""),
            host_data.get("image_uri"),
            host_data.get("thumbnail_uri"),
            1 if host_data.get("is_active", True) else 0,
            host_data.get("location"),
            host_data.get("uri"),
        ),
    )


def save_program(conn: sqlite3.Connection, program_data: dict[str, Any]) -> None:
    program_id = program_data.get("id")
    if not isinstance(program_id, int):
        return

    conn.execute(
        """
        INSERT INTO program (
            program_id, name, description, tags, image_uri,
            thumbnail_uri, is_active, location, location_name, uri
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(program_id) DO UPDATE SET
            name = excluded.name,
            description = excluded.description,
            tags = excluded.tags,
            image_uri = excluded.image_uri,
            thumbnail_uri = excluded.thumbnail_uri,
            is_active = excluded.is_active,
            location = excluded.location,
            location_name = excluded.location_name,
            uri = excluded.uri;
        """,
        (
            program_id,
            program_data.get("name", ""),
            program_data.get("description"),
            program_data.get("tags"),
            program_data.get("image_uri"),
            program_data.get("thumbnail_uri"),
            1 if program_data.get("is_active", True) else 0,
            program_data.get("location"),
            program_data.get("location_name"),
            program_data.get("uri"),
        ),
    )


def save_show(conn: sqlite3.Connection, show_data: dict[str, Any]) -> None:
    show_id = show_data.get("id")
    if not isinstance(show_id, int):
        return

    program_id = show_data.get("program")
    if isinstance(program_id, int):
        conn.execute(
            "INSERT OR IGNORE INTO program (program_id, name) VALUES (?, ?);",
            (program_id, show_data.get("program_name") or "Unknown Program"),
        )

    utc_start_time = parse_iso_to_utc(show_data.get("start_time")) or ""

    conn.execute(
        """
        INSERT INTO show (
            show_id, program_id, start_time, tagline, image_uri,
            program_image_uri, location, location_name, uri
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(show_id) DO UPDATE SET
            program_id = excluded.program_id,
            start_time = excluded.start_time,
            tagline = excluded.tagline,
            image_uri = excluded.image_uri,
            program_image_uri = excluded.program_image_uri,
            location = excluded.location,
            location_name = excluded.location_name,
            uri = excluded.uri;
        """,
        (
            show_id,
            program_id,
            utc_start_time,
            show_data.get("tagline"),
            show_data.get("image_uri"),
            show_data.get("program_image_uri"),
            show_data.get("location"),
            show_data.get("location_name"),
            show_data.get("uri"),
        ),
    )

    hosts = show_data.get("hosts") or []
    for host_id in hosts:
        if isinstance(host_id, int):
            conn.execute(
                "INSERT OR IGNORE INTO host (host_id, name) VALUES (?, ?);",
                (host_id, "Unknown Host"),
            )
            conn.execute(
                "INSERT OR IGNORE INTO show_jx_host (show_id, host_id) VALUES (?, ?);",
                (show_id, host_id),
            )


def save_timeslot(conn: sqlite3.Connection, timeslot_data: dict[str, Any]) -> None:
    timeslot_id = timeslot_data.get("id")
    program_id = timeslot_data.get("program")
    if not isinstance(timeslot_id, int) or not isinstance(program_id, int):
        return

    conn.execute(
        "INSERT OR IGNORE INTO program (program_id, name) VALUES (?, ?);",
        (program_id, timeslot_data.get("program_name") or "Unknown Program"),
    )

    conn.execute(
        """
        INSERT INTO timeslot (
            timeslot_id, program_id, weekday, start_date, end_date,
            start_time, end_time, duration, uri
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(timeslot_id) DO UPDATE SET
            program_id = excluded.program_id,
            weekday = excluded.weekday,
            start_date = excluded.start_date,
            end_date = excluded.end_date,
            start_time = excluded.start_time,
            end_time = excluded.end_time,
            duration = excluded.duration,
            uri = excluded.uri;
        """,
        (
            timeslot_id,
            program_id,
            timeslot_data.get("weekday", 0),
            timeslot_data.get("start_date", ""),
            timeslot_data.get("end_date"),
            timeslot_data.get("start_time", ""),
            timeslot_data.get("end_time", ""),
            timeslot_data.get("duration"),
            timeslot_data.get("uri"),
        ),
    )

    hosts = timeslot_data.get("hosts") or []
    for host_id in hosts:
        if isinstance(host_id, int):
            conn.execute(
                "INSERT OR IGNORE INTO host (host_id, name) VALUES (?, ?);",
                (host_id, "Unknown Host"),
            )
            conn.execute(
                "INSERT OR IGNORE INTO timeslot_jx_host (timeslot_id, host_id) VALUES (?, ?);",  # noqa: E501
                (timeslot_id, host_id),
            )


def resolve_artist(conn: sqlite3.Connection, record: JsonResultsForDb) -> int | None:
    if not record.artist_name:
        return None
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR IGNORE INTO artist (artist_name, artist_brainz, is_local)
        VALUES (?, ?, ?);
        """,
        (
            record.artist_name,
            record.artist_brainz,
            1 if str(record.is_local).lower() in ("true", "1") else 0,
        ),
    )
    if record.artist_brainz:
        cursor.execute(
            "SELECT artist_ref FROM artist WHERE artist_brainz = ?;",
            (record.artist_brainz,),
        )
    else:
        cursor.execute(
            "SELECT artist_ref FROM artist WHERE artist_name = ?;",
            (record.artist_name,),
        )
    row = cursor.fetchone()
    return row[0] if row else None


def resolve_label(conn: sqlite3.Connection, record: JsonResultsForDb) -> int | None:
    if not record.label_name:
        return None
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR IGNORE INTO label (label_name, label_brainz)
        VALUES (?, ?);
        """,
        (record.label_name, record.label_brainz),
    )
    if record.label_brainz:
        cursor.execute(
            "SELECT label_ref FROM label WHERE label_brainz = ?;",
            (record.label_brainz,),
        )
    else:
        cursor.execute(
            "SELECT label_ref FROM label WHERE label_name = ?;",
            (record.label_name,),
        )
    row = cursor.fetchone()
    return row[0] if row else None


def resolve_album(
    conn: sqlite3.Connection,
    record: JsonResultsForDb,
    artist_ref: int,
    label_ref: int | None,
) -> int | None:
    if not record.album_name:
        return None
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR IGNORE INTO album (
            album_name, release_brainz, release_group_brainz, artist_ref, label_ref
        ) VALUES (?, ?, ?, ?, ?);
        """,
        (
            record.album_name,
            record.release_brainz,
            record.release_group_brainz,
            artist_ref,
            label_ref,
        ),
    )
    if record.release_brainz:
        cursor.execute(
            "SELECT album_ref FROM album WHERE release_brainz = ?;",
            (record.release_brainz,),
        )
    else:
        cursor.execute(
            "SELECT album_ref FROM album WHERE album_name = ? AND artist_ref = ?;",
            (record.album_name, artist_ref),
        )
    row = cursor.fetchone()
    return row[0] if row else None


def resolve_track(
    conn: sqlite3.Connection,
    record: JsonResultsForDb,
    artist_ref: int,
    album_ref: int | None,
) -> int | None:
    if not record.track_name:
        return None
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR IGNORE INTO track (
            track_name, track_brainz, recording_brainz, release_date, artist_ref, album_ref
        ) VALUES (?, ?, ?, ?, ?, ?);
        """,  # noqa: E501
        (
            record.track_name,
            record.track_brainz,
            record.recording_brainz,
            record.release_date,
            artist_ref,
            album_ref,
        ),
    )
    if record.recording_brainz:
        cursor.execute(
            "SELECT track_ref FROM track WHERE recording_brainz = ?;",
            (record.recording_brainz,),
        )
    else:
        cursor.execute(
            """
            SELECT track_ref FROM track
            WHERE track_name = ? AND artist_ref = ? AND IFNULL(album_ref, -1) = IFNULL(?, -1);
            """,  # noqa: E501
            (record.track_name, artist_ref, album_ref),
        )
    row = cursor.fetchone()
    return row[0] if row else None


def get_oldest_timestamp(conn: sqlite3.Connection, endpoint: str) -> str | None:
    """Returns the earliest recorded timestamp for pagination backfills."""
    cursor = conn.cursor()
    if endpoint == "plays":
        cursor.execute(
            "SELECT airdate FROM play WHERE airdate IS NOT NULL ORDER BY airdate LIMIT 1;"  # noqa: E501
        )
    elif endpoint == "shows":
        cursor.execute(
            "SELECT start_time FROM show WHERE start_time IS NOT NULL ORDER BY start_time LIMIT 1;"  # noqa: E501
        )
    else:
        return None

    row = cursor.fetchone()
    return row[0] if row and isinstance(row[0], str) else None


def get_latest_timestamp(conn: sqlite3.Connection, endpoint: str) -> str | None:
    """Returns the newest recorded timestamp for forward-filling."""
    cursor = conn.cursor()
    if endpoint == "plays":
        cursor.execute(
            "SELECT airdate FROM play WHERE airdate IS NOT NULL ORDER BY airdate DESC LIMIT 1;"  # noqa: E501
        )
    elif endpoint == "shows":
        cursor.execute(
            "SELECT start_time FROM show WHERE start_time IS NOT NULL ORDER BY start_time DESC LIMIT 1;"  # noqa: E501
        )
    else:
        return None

    row = cursor.fetchone()
    return row[0] if row and isinstance(row[0], str) else None


def get_latest_play(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Retrieves the newest music play joined with its resolved metadata."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT 
            p.play_id,
            p.airdate,
            p.play_type,
            t.track_ref,
            t.track_name,
            a.artist_ref,
            a.artist_name,
            al.album_ref,
            al.album_name
        FROM play p
        JOIN track t ON p.track_ref = t.track_ref
        JOIN artist a ON t.artist_ref = a.artist_ref
        LEFT JOIN album al ON t.album_ref = al.album_ref
        WHERE p.play_type = 'trackplay'
        ORDER BY p.airdate DESC
        LIMIT 1;
        """
    )
    row = cursor.fetchone()
    if not row:
        return None
    return {
        "play_id": row[0],
        "airdate": row[1],
        "play_type": row[2],
        "track_ref": row[3],
        "track_name": row[4],
        "artist_ref": row[5],
        "artist_name": row[6],
        "album_ref": row[7],
        "album_name": row[8],
    }


def save_batch(conn: sqlite3.Connection, batch: list[JsonResultsForDb]) -> int:
    inserted_plays = 0
    sql_play = """
    INSERT OR IGNORE INTO play (
        play_id, airdate, show_id, play_type, track_ref,
        is_request, is_live, rotation_status, comment,
        location, location_name,image_uri, thumbnail_uri,
        play_uri, show_uri
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """
    with conn:
        cursor = conn.cursor()
        for record in batch:
            if record.play_id is None or record.airdate is None:
                continue

            if record.show_id is not None:
                cursor.execute(
                    "INSERT OR IGNORE INTO show (show_id, start_time) VALUES (?, ?);",
                    (record.show_id, record.airdate),
                )

            artist_ref = resolve_artist(conn, record)
            label_ref = resolve_label(conn, record)
            album_ref = (
                resolve_album(conn, record, artist_ref, label_ref)
                if artist_ref
                else None
            )
            track_ref = (
                resolve_track(conn, record, artist_ref, album_ref)
                if artist_ref
                else None
            )

            is_req = 1 if str(record.is_request).lower() in ("true", "1") else 0
            is_liv = 1 if str(record.is_live).lower() in ("true", "1") else 0

            cursor.execute(
                sql_play,
                (
                    record.play_id,
                    record.airdate,
                    record.show_id,
                    record.play_type,
                    track_ref,
                    is_req,
                    is_liv,
                    record.rotation_status,
                    record.comment,
                    record.location,
                    record.location_name,
                    record.image_uri,
                    record.thumbnail_uri,
                    record.play_uri,
                    record.show_uri,
                ),
            )
            inserted_plays += cursor.rowcount

            if record.raw_json:
                save_raw_payload(conn, "plays", record.play_id, record.raw_json)

    return inserted_plays


def save_spotify_track_match(
    conn: sqlite3.Connection,
    track_ref: int,
    spotify_uri: str,
    spotify_name: str | None = None,
) -> None:
    """Saves or updates Spotify track URI link."""
    conn.execute(
        """
        INSERT INTO spotify_track (track_ref, spotify_track_uri, spotify_track_name)
        VALUES (?, ?, ?)
        ON CONFLICT(track_ref) DO UPDATE SET
            spotify_track_uri = excluded.spotify_track_uri,
            spotify_track_name = excluded.spotify_track_name,
            matched_at = datetime('now');
        """,
        (track_ref, spotify_uri, spotify_name),
    )


def get_spotify_track_uri(conn: sqlite3.Connection, track_ref: int) -> str | None:
    """Fetches mapped Spotify URI for a track_ref if previously discovered."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT spotify_track_uri FROM spotify_track WHERE track_ref = ?;",
        (track_ref,),
    )
    row = cursor.fetchone()
    return row[0] if row else None
