"""Schema and queries for the FastAPI backend.

Extends the Streamlit-era schema (root-level db.py) with a real `users`
table. `analyses.user_name` (free-text, spoofable -- anyone typing the same
name saw that name's history) is replaced by `analyses.user_id`, a foreign
key into `users`. Existing rows are migrated by matching the old free-text
name to a placeholder user of the same name, so history isn't silently
dropped on cutover; new rows are written with a real authenticated user id.
"""

import os

import psycopg
from psycopg.types.json import Jsonb

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS analyses (
    id SERIAL PRIMARY KEY,
    video_id TEXT NOT NULL,
    title TEXT NOT NULL,
    channel TEXT NOT NULL,
    analyzed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    result_json JSONB NOT NULL,
    input_fingerprint TEXT NOT NULL DEFAULT ''
);
-- CREATE TABLE IF NOT EXISTS is a no-op against the table the Streamlit app
-- already created (video_id/title/channel/user_name/...), so the new column
-- needs its own ALTER TABLE, same as user_name did when it was added there.
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id);
CREATE INDEX IF NOT EXISTS idx_analyses_user_id ON analyses(user_id);
CREATE INDEX IF NOT EXISTS idx_analyses_video_fingerprint
    ON analyses(video_id, input_fingerprint, analyzed_at DESC);
"""


def get_connection() -> psycopg.Connection | None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return None
    try:
        return psycopg.connect(database_url, connect_timeout=10)
    except psycopg.OperationalError:
        return None


def ensure_schema(conn: psycopg.Connection) -> bool:
    try:
        conn.execute(_SCHEMA)
        conn.commit()
        return True
    except psycopg.Error:
        try:
            conn.rollback()
        except psycopg.Error:
            pass
        return False


# ------------------------------------------------------------------- users


def create_user(conn: psycopg.Connection, email: str, password_hash: str, display_name: str) -> dict:
    row = conn.execute(
        "INSERT INTO users (email, password_hash, display_name) VALUES (%s, %s, %s) "
        "RETURNING id, email, display_name",
        (email.lower().strip(), password_hash, display_name.strip()),
    ).fetchone()
    conn.commit()
    return {"id": row[0], "email": row[1], "display_name": row[2]}


def get_user_by_email(conn: psycopg.Connection, email: str) -> dict | None:
    row = conn.execute(
        "SELECT id, email, password_hash, display_name FROM users WHERE email = %s",
        (email.lower().strip(),),
    ).fetchone()
    if row is None:
        return None
    return {"id": row[0], "email": row[1], "password_hash": row[2], "display_name": row[3]}


def get_user_by_id(conn: psycopg.Connection, user_id: int) -> dict | None:
    row = conn.execute(
        "SELECT id, email, display_name FROM users WHERE id = %s", (user_id,),
    ).fetchone()
    if row is None:
        return None
    return {"id": row[0], "email": row[1], "display_name": row[2]}


# ---------------------------------------------------------------- analyses


def save_analysis(
    conn: psycopg.Connection, user_id: int, video_id: str, title: str, channel: str,
    result: dict, input_fingerprint: str = "",
) -> int:
    row = conn.execute(
        "INSERT INTO analyses (user_id, video_id, title, channel, result_json, input_fingerprint) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (user_id, video_id, title, channel, Jsonb(result), input_fingerprint),
    ).fetchone()
    conn.commit()
    return row[0]


def list_recent(conn: psycopg.Connection, user_id: int, limit: int = 10, search: str = "") -> list[dict]:
    if search:
        rows = conn.execute(
            "SELECT id, video_id, title, channel, analyzed_at FROM analyses "
            "WHERE user_id = %s AND (title ILIKE %s OR channel ILIKE %s) "
            "ORDER BY analyzed_at DESC LIMIT %s",
            (user_id, f"%{search}%", f"%{search}%", limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, video_id, title, channel, analyzed_at FROM analyses "
            "WHERE user_id = %s ORDER BY analyzed_at DESC LIMIT %s",
            (user_id, limit),
        ).fetchall()
    return [
        {"id": r[0], "video_id": r[1], "title": r[2], "channel": r[3], "analyzed_at": r[4].isoformat()}
        for r in rows
    ]


def get_cached_analysis(conn: psycopg.Connection, video_id: str, input_fingerprint: str) -> dict | None:
    """Not scoped by user -- see root db.py's identical function for why:
    the analysis is a property of the video's public content, not of who
    clicked Analyze."""
    row = conn.execute(
        "SELECT result_json FROM analyses WHERE video_id = %s AND input_fingerprint = %s "
        "ORDER BY analyzed_at DESC LIMIT 1",
        (video_id, input_fingerprint),
    ).fetchone()
    return row[0] if row else None


def get_analysis(conn: psycopg.Connection, user_id: int, analysis_id: int) -> dict | None:
    row = conn.execute(
        "SELECT result_json FROM analyses WHERE id = %s AND user_id = %s",
        (analysis_id, user_id),
    ).fetchone()
    return row[0] if row else None
