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

CREATE TABLE IF NOT EXISTS channels (
    id SERIAL PRIMARY KEY,
    channel_id TEXT NOT NULL UNIQUE,
    handle TEXT NOT NULL,
    title TEXT NOT NULL,
    thumbnail_url TEXT NOT NULL DEFAULT '',
    last_ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS channel_videos (
    id SERIAL PRIMARY KEY,
    channel_id TEXT NOT NULL,
    video_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    tags JSONB NOT NULL,
    published_at TIMESTAMPTZ,
    duration_seconds INT NOT NULL DEFAULT 0,
    view_count BIGINT NOT NULL DEFAULT 0,
    like_count BIGINT NOT NULL DEFAULT 0,
    comment_count BIGINT NOT NULL DEFAULT 0,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_channel_videos_channel ON channel_videos(channel_id, fetched_at DESC);
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


# ---------------------------------------------------------------- channels
#
# Channel data is public (anyone can read it from the YouTube API with just a
# handle), so unlike `analyses` it is never scoped by user_name -- one
# ingest is shared by everyone who looks up that channel. Each ingest INSERTs
# a fresh batch of channel_videos rows rather than UPDATEing existing ones
# (a snapshot, keyed by fetched_at) so that a second ingest weeks later
# preserves the earlier view counts too -- that history is what would let a
# future feature compute view velocity, and it can't be reconstructed after
# the fact if snapshots overwrite each other.


def upsert_channel(conn: psycopg.Connection, channel_id: str, handle: str, title: str, thumbnail_url: str) -> None:
    conn.execute(
        """
        INSERT INTO channels (channel_id, handle, title, thumbnail_url, last_ingested_at)
        VALUES (%s, %s, %s, %s, now())
        ON CONFLICT (channel_id) DO UPDATE SET
            handle = EXCLUDED.handle,
            title = EXCLUDED.title,
            thumbnail_url = EXCLUDED.thumbnail_url,
            last_ingested_at = now()
        """,
        (channel_id, handle, title, thumbnail_url),
    )
    conn.commit()


def save_channel_videos(conn: psycopg.Connection, channel_id: str, videos: list) -> None:
    """videos: list of channel.ChannelVideo. One INSERT per video, all sharing
    the same fetched_at batch (default now()) so a later query can group by
    ingest run if needed."""
    for v in videos:
        conn.execute(
            """
            INSERT INTO channel_videos
                (channel_id, video_id, title, description, tags, published_at,
                 duration_seconds, view_count, like_count, comment_count)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                channel_id, v.video_id, v.title, v.description, Jsonb(v.tags),
                v.published_at or None, v.duration_seconds,
                v.view_count, v.like_count, v.comment_count,
            ),
        )
    conn.commit()


def get_channel(conn: psycopg.Connection, channel_id: str) -> dict | None:
    row = conn.execute(
        "SELECT channel_id, handle, title, thumbnail_url, last_ingested_at "
        "FROM channels WHERE channel_id = %s",
        (channel_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "channel_id": row[0], "handle": row[1], "title": row[2],
        "thumbnail_url": row[3], "last_ingested_at": row[4],
    }


def get_latest_channel_videos(conn: psycopg.Connection, channel_id: str) -> list:
    """Most recent snapshot row per video_id -- the current view of the
    channel, ignoring older snapshots kept only for future velocity tracking.
    Returns channel.ChannelVideo instances (imported locally to avoid a
    module-level circular import, since channel.py doesn't import db.py)."""
    from channel import ChannelVideo

    rows = conn.execute(
        """
        SELECT DISTINCT ON (video_id)
            video_id, title, description, tags, published_at,
            duration_seconds, view_count, like_count, comment_count
        FROM channel_videos
        WHERE channel_id = %s
        ORDER BY video_id, fetched_at DESC
        """,
        (channel_id,),
    ).fetchall()
    return [
        ChannelVideo(
            video_id=r[0], title=r[1], description=r[2], tags=r[3],
            published_at=r[4].isoformat() if r[4] else "",
            duration_seconds=r[5], view_count=r[6], like_count=r[7], comment_count=r[8],
        )
        for r in rows
    ]
