import sqlite3
from pathlib import Path

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


def resolve_artist(conn: sqlite3.Connection, record: JsonResultsForDb) -> int | None:
    if not record.artist_name:
        return None
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR IGNORE INTO artist (artist_name, artist_brainz, is_local)
        VALUES (?, ?, ?);
        """,
        (record.artist_name, record.artist_brainz, record.is_local),
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
            "SELECT label_ref FROM label WHERE label_name = ?;", (record.label_name,)
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
        """,
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
            """,
            (record.track_name, artist_ref, album_ref),
        )

    row = cursor.fetchone()
    return row[0] if row else None


def save_batch(conn: sqlite3.Connection, batch: list[JsonResultsForDb]) -> int:
    inserted_plays = 0
    sql_play = """
    INSERT OR IGNORE INTO play (
        play_id, airdate, show_id, play_type, track_ref,
        is_request, is_live, rotation_status, comment,
        location, location_name, play_uri, show_uri,
        image_uri, thumbnail_uri
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """
    sql_json = "INSERT OR IGNORE INTO json (play_id, raw_json) VALUES (?, ?);"

    with conn:
        cursor = conn.cursor()
        for record in batch:
            if record.play_id is None:
                continue

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

            cursor.execute(
                sql_play,
                (
                    record.play_id,
                    record.airdate,
                    record.show_id,
                    record.play_type,
                    track_ref,
                    record.is_request,
                    record.is_live,
                    record.rotation_status,
                    record.comment,
                    record.location,
                    record.location_name,
                    record.play_uri,
                    record.show_uri,
                    record.image_uri,
                    record.thumbnail_uri,
                ),
            )
            inserted_plays += cursor.rowcount

            if record.raw_json:
                cursor.execute(sql_json, (record.play_id, record.raw_json))

    return inserted_plays
