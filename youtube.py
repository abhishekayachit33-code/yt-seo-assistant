import re
import uuid
from dataclasses import dataclass

import requests

_ID_PATTERNS = [
    r"(?:youtube\.com/watch\?v=|youtube\.com/shorts/|youtube\.com/embed/|youtu\.be/)([A-Za-z0-9_-]{11})",
]


class InvalidURLError(ValueError):
    pass


class VideoNotFoundError(ValueError):
    pass


@dataclass
class VideoMeta:
    video_id: str
    title: str
    description: str
    tags: list[str]
    channel_title: str
    thumbnail_url: str
    published_at: str = ""
    view_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    category_id: str = ""
    is_planned: bool = False


def build_planned_meta(title: str, description: str, tags: list[str], channel_title: str) -> VideoMeta:
    """Synthetic VideoMeta for a video that doesn't exist on YouTube yet -- lets
    the rest of the app (health score, SEO diff, competitor gap, exports,
    history) work unmodified on a draft. video_id is 'planned-<12 hex chars>'
    (20 chars), which can never collide with a real 11-char YouTube ID, so it
    doubles as the "was this planned" signal anywhere a video_id string is
    available -- including on reload from history, with no DB migration."""
    return VideoMeta(
        video_id=f"planned-{uuid.uuid4().hex[:12]}",
        title=title,
        description=description,
        tags=tags,
        channel_title=channel_title,
        thumbnail_url="",
        published_at="",
        view_count=0,
        like_count=0,
        comment_count=0,
        category_id="",
        is_planned=True,
    )


def parse_video_id(url: str) -> str:
    url = url.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
        return url
    for pattern in _ID_PATTERNS:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise InvalidURLError(f"Could not extract a video ID from: {url}")


def _as_int(value) -> int:
    """Statistics come back as strings, and creators can hide like or comment
    counts entirely -- a missing field is 0, not an error."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def fetch_metadata(video_id: str, api_key: str) -> VideoMeta:
    # 'statistics' rides along on the same request as 'snippet': videos.list is
    # 1 quota unit regardless of how many parts are asked for.
    response = requests.get(
        "https://www.googleapis.com/youtube/v3/videos",
        params={"part": "snippet,statistics", "id": video_id, "key": api_key},
        timeout=10,
    )
    response.raise_for_status()
    items = response.json().get("items", [])
    if not items:
        raise VideoNotFoundError(f"No video found for ID: {video_id}")
    snippet = items[0]["snippet"]
    statistics = items[0].get("statistics", {})
    thumbnails = snippet.get("thumbnails", {})
    thumbnail_url = (
        thumbnails.get("high", {}).get("url")
        or thumbnails.get("default", {}).get("url", "")
    )
    return VideoMeta(
        video_id=video_id,
        title=snippet.get("title", ""),
        description=snippet.get("description", ""),
        tags=snippet.get("tags", []),
        channel_title=snippet.get("channelTitle", ""),
        thumbnail_url=thumbnail_url,
        published_at=snippet.get("publishedAt", ""),
        view_count=_as_int(statistics.get("viewCount")),
        like_count=_as_int(statistics.get("likeCount")),
        comment_count=_as_int(statistics.get("commentCount")),
        category_id=str(snippet.get("categoryId", "")),
    )
