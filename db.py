import json
import os

import psycopg
from psycopg.types.json import Jsonb

_SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    id SERIAL PRIMARY KEY,
    video_id TEXT NOT NULL,
    title TEXT NOT NULL,
    channel TEXT NOT NULL,
    analyzed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    result_json JSONB NOT NULL
);
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS user_name TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_analyses_user_name ON analyses(user_name);
CREATE INDEX IF NOT EXISTS idx_analyses_user_video ON analyses(user_name, video_id);
"""


def get_connection() -> psycopg.Connection | None:
    """None if DATABASE_URL isn't set or the DB isn't reachable -- history is
    a nice-to-have, the app must still work without it.

    Deliberately does NOT run the schema here. Callers that cache this
    connection (e.g. Streamlit's st.cache_resource, which can outlive a code
    deploy if the host does a script-level reload rather than a full process
    restart) would otherwise cache a connection from before a later schema
    change and never pick it up -- exactly what happened when user_name was
    added: the cached connection predated that code, so the ALTER TABLE
    never ran against it. Call ensure_schema() separately, every time,
    regardless of whether the connection itself is cached."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return None
    try:
        # 3s was tuned for the always-on in-cluster Postgres. Serverless
        # providers (Neon, etc.) suspend on idle and take a few seconds to
        # wake on the next connection -- too tight a timeout here means the
        # first request after idle looks identical to "unreachable".
        return psycopg.connect(database_url, connect_timeout=10)
    except psycopg.OperationalError:
        return None


def ensure_schema(conn: psycopg.Connection) -> bool:
    """Idempotent -- every statement is IF NOT EXISTS, so safe and cheap to
    call on every request even against a long-lived cached connection.
    Returns False (rather than raising) if the connection has gone stale,
    e.g. a serverless provider dropping it after idle suspend."""
    try:
        conn.execute(_SCHEMA)
        conn.commit()
        return True
    except psycopg.Error:
        try:
            conn.rollback()
        except psycopg.Error:
            pass  # connection itself is dead, not just the transaction -- nothing to roll back
        return False


def save_analysis(conn: psycopg.Connection, user_name: str, video_id: str, title: str, channel: str, result: dict) -> None:
    conn.execute(
        "INSERT INTO analyses (user_name, video_id, title, channel, result_json) VALUES (%s, %s, %s, %s, %s)",
        (user_name, video_id, title, channel, Jsonb(result)),
    )
    conn.commit()


def list_recent(conn: psycopg.Connection, user_name: str, limit: int = 10, search: str = "") -> list[dict]:
    """search matches title or channel, case-insensitive substring."""
    if search:
        rows = conn.execute(
            "SELECT id, video_id, title, channel, analyzed_at FROM analyses "
            "WHERE user_name = %s AND (title ILIKE %s OR channel ILIKE %s) "
            "ORDER BY analyzed_at DESC LIMIT %s",
            (user_name, f"%{search}%", f"%{search}%", limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, video_id, title, channel, analyzed_at FROM analyses "
            "WHERE user_name = %s ORDER BY analyzed_at DESC LIMIT %s",
            (user_name, limit),
        ).fetchall()
    return [
        {"id": r[0], "video_id": r[1], "title": r[2], "channel": r[3], "analyzed_at": r[4]}
        for r in rows
    ]


def get_cached_analysis(conn: psycopg.Connection, user_name: str, video_id: str) -> dict | None:
    """Most recent saved analysis for this exact video, scoped to the user --
    lets a repeat "Analyze" on the same URL skip the Gemini call entirely."""
    row = conn.execute(
        "SELECT result_json FROM analyses WHERE user_name = %s AND video_id = %s "
        "ORDER BY analyzed_at DESC LIMIT 1",
        (user_name, video_id),
    ).fetchone()
    if row is None:
        return None
    return row[0] if isinstance(row[0], dict) else json.loads(row[0])


def get_analysis(conn: psycopg.Connection, user_name: str, analysis_id: int) -> dict | None:
    """Scoped to user_name too, not just id -- otherwise one user could load
    another's saved analysis by guessing/incrementing the id."""
    row = conn.execute(
        "SELECT result_json FROM analyses WHERE id = %s AND user_name = %s",
        (analysis_id, user_name),
    ).fetchone()
    if row is None:
        return None
    return row[0] if isinstance(row[0], dict) else json.loads(row[0])
