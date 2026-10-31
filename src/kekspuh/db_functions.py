import sqlite3
from pathlib import Path
from typing import Any

from kekspuh.models import JsonResultsForDb

DB_PATH = Path("./data/kekspuh.db")


def connect_db(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA cache_size=-64000;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    conn.execute("PRAGMA foreign_keys=ON;")

    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS artist (
                artist_ref INTEGER PRIMARY KEY AUTOINCREMENT,
                artist_name TEXT NOT NULL,
                artist_brainz TEXT,
                is_local TEXT
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

            CREATE TABLE IF NOT EXISTS play (
                play_id INTEGER PRIMARY KEY,
                airdate TEXT NOT NULL,
                show_id INTEGER,
                play_type TEXT,
                track_ref INTEGER,
                is_request TEXT,
                is_live TEXT,
                rotation_status TEXT,
                comment TEXT,
                location TEXT,
                location_name TEXT,
                play_uri TEXT,
                show_uri TEXT,
                image_uri TEXT,
                thumbnail_uri TEXT,
                FOREIGN KEY (track_ref) REFERENCES track(track_ref) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS json (
                play_id INTEGER PRIMARY KEY,
                raw_json TEXT NOT NULL,
                FOREIGN KEY (play_id) REFERENCES play(play_id) ON DELETE CASCADE
            );

            -- Artist Deduplication Indexes
            CREATE UNIQUE INDEX IF NOT EXISTS idx_artist_brainz
                ON artist(artist_brainz)
                WHERE artist_brainz IS NOT NULL;

            CREATE UNIQUE INDEX IF NOT EXISTS idx_artist_name_fallback
                ON artist(artist_name)
                WHERE artist_brainz IS NULL;

            -- Label Deduplication Indexes
            CREATE UNIQUE INDEX IF NOT EXISTS idx_label_brainz
                ON label(label_brainz)
                WHERE label_brainz IS NOT NULL;

            CREATE UNIQUE INDEX IF NOT EXISTS idx_label_name_fallback
                ON label(label_name)
                WHERE label_brainz IS NULL;

            -- Album Deduplication Indexes
            CREATE UNIQUE INDEX IF NOT EXISTS idx_album_brainz
                ON album(release_brainz)
                WHERE release_brainz IS NOT NULL;

            CREATE UNIQUE INDEX IF NOT EXISTS idx_album_composite_fallback
                ON album(album_name, artist_ref)
                WHERE release_brainz IS NULL;

            -- Track Deduplication Indexes
            CREATE UNIQUE INDEX IF NOT EXISTS idx_track_recording_brainz
                ON track(recording_brainz)
                WHERE recording_brainz IS NOT NULL;

            CREATE UNIQUE INDEX IF NOT EXISTS idx_track_composite_fallback
                ON track(track_name, artist_ref, IFNULL(album_ref, -1))
                WHERE recording_brainz IS NULL;

            -- Performance Query Indexes
            CREATE INDEX IF NOT EXISTS idx_play_airdate ON play(airdate);
            CREATE INDEX IF NOT EXISTS idx_play_track_ref ON play(track_ref);
            CREATE INDEX IF NOT EXISTS idx_track_artist_ref ON track(artist_ref);
            CREATE INDEX IF NOT EXISTS idx_album_artist_ref ON album(artist_ref);
            """
        )


def get_oldest_airdate(conn: sqlite3.Connection) -> str | None:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT airdate
        FROM play
        WHERE airdate IS NOT NULL
        ORDER BY airdate ASC
        LIMIT 1;
        """
    )
    row = cursor.fetchone()
    return row[0] if row and isinstance(row[0], str) else None


def save_batch(conn: sqlite3.Connection, batch: list[JsonResultsForDb]) -> int:
    sql_artist = """
    INSERT OR IGNORE INTO artist (
    artist_name, artist_brainz, is_local
    ) VALUES (?, ?)
    """

    sql_label = """
    INSERT OR IGNORE INTO label (
    label_name, label_brainz
    ) VALUES (?, ?)
    """

    sql_album = """
    INSERT OR IGNORE INTO album (
    album_name, release_brainz, release_group_brainz,
    artist_ref, label_ref
    ) VALUES (?, ?, ?, ?, ?)
    """

    sql_track = """
    INSERT OR IGNORE INTO track (
    track_name, track_brainz, recording_brainz,
    release_date, artist_ref, album_ref
    ) VALUES (?, ?, ?, ?, ?, ?)
    """

    sql_play = """
    INSERT OR IGNORE INTO play (
    play_id, airdate, show_id, play_type, track_ref,
    is_request, is_live, rotation_status, comment,
    location, location_name, play_uri, show_uri,
    image_uri, thumbnail_uri
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    sql_json = """
    INSERT OR IGNORE INTO json (
    play_id, raw_json
    ) VALUES (?, ?)
    """

    artist_params: list[Any] = []
    label_params: list[Any] = []
    album_params: list[Any] = []
    track_params: list[Any] = []
    play_params: list[Any] = []
    json_params: list[Any] = []

    for art in batch:
        if art.artist_name is None:
            continue
        artist_params.append(
            (art.artist_name, art.artist_brainz, art.is_local)
        )

    for lab in batch:
        if lab.label_name is None:
            continue
        label_params.append(
            (
                lab.label_name,
                lab.label_brainz,
            )
        )

    for alb in batch:
        if alb.album_name is None:
            continue
        album_params.append(
            (
                alb.album_name,
                alb.release_brainz,
                alb.release_group_brainz,
            )
        )

    for trk in batch:
        if trk.track_name is None:
            continue
        track_params.append(
            (
                trk.track_name,
                trk.track_brainz,
                trk.recording_brainz,
                trk.release_date,
            )
        )
    for play in batch:
        if play.play_id is None:
            continue
        play_params.append(
            (
                play.play_id,
                play.airdate,
                play.show_id,
                play.play_type,
                play.is_request,
                play.is_live,
                play.rotation_status,
                play.comment,
                play.location,
                play.location_name,
                play.play_uri,
                play.show_uri,
                play.image_uri,
                play.thumbnail_uri,
            )
        )

    for jsn in batch:
        if jsn.raw_json is None:
            continue
        json_params.append((jsn.play_id, jsn.raw_json))

    with conn:
        cursor = conn.executemany(sql_artist, artist_params)
        cursor = conn.executemany(sql_label, label_params)
        cursor = conn.executemany(sql_album, album_params)
        cursor = conn.executemany(sql_track, track_params)
        cursor = conn.executemany(sql_play, play_params)
        cursor = conn.executemany(sql_json, json_params)
        inserted_count = cursor.rowcount
        return inserted_count
