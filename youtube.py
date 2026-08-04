import re
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


def parse_video_id(url: str) -> str:
    url = url.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
        return url
    for pattern in _ID_PATTERNS:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise InvalidURLError(f"Could not extract a video ID from: {url}")


def fetch_metadata(video_id: str, api_key: str) -> VideoMeta:
    response = requests.get(
        "https://www.googleapis.com/youtube/v3/videos",
        params={"part": "snippet", "id": video_id, "key": api_key},
        timeout=10,
    )
    response.raise_for_status()
    items = response.json().get("items", [])
    if not items:
        raise VideoNotFoundError(f"No video found for ID: {video_id}")
    snippet = items[0]["snippet"]
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
    )
