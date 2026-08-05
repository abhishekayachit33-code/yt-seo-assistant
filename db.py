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
"""


def get_connection() -> psycopg.Connection | None:
    """None if DATABASE_URL isn't set or the DB isn't reachable -- history is
    a nice-to-have, the app must still work without it."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return None
    try:
        # 3s was tuned for the always-on in-cluster Postgres. Serverless
        # providers (Neon, etc.) suspend on idle and take a few seconds to
        # wake on the next connection -- too tight a timeout here means the
        # first request after idle looks identical to "unreachable".
        conn = psycopg.connect(database_url, connect_timeout=10)
        conn.execute(_SCHEMA)
        conn.commit()
        return conn
    except psycopg.OperationalError:
        return None


def save_analysis(conn: psycopg.Connection, video_id: str, title: str, channel: str, result: dict) -> None:
    conn.execute(
        "INSERT INTO analyses (video_id, title, channel, result_json) VALUES (%s, %s, %s, %s)",
        (video_id, title, channel, Jsonb(result)),
    )
    conn.commit()


def list_recent(conn: psycopg.Connection, limit: int = 10) -> list[dict]:
    rows = conn.execute(
        "SELECT id, video_id, title, channel, analyzed_at FROM analyses ORDER BY analyzed_at DESC LIMIT %s",
        (limit,),
    ).fetchall()
    return [
        {"id": r[0], "video_id": r[1], "title": r[2], "channel": r[3], "analyzed_at": r[4]}
        for r in rows
    ]


def get_analysis(conn: psycopg.Connection, analysis_id: int) -> dict | None:
    row = conn.execute(
        "SELECT result_json FROM analyses WHERE id = %s", (analysis_id,)
    ).fetchone()
    if row is None:
        return None
    return row[0] if isinstance(row[0], dict) else json.loads(row[0])
