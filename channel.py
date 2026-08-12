"""Channel-level ingest: pull every public video on a channel via the YouTube
Data API, no OAuth required. Two-step API dance: resolve the handle to a
channel_id + uploads playlist, page through that playlist for video ids, then
batch-fetch stats for those ids 50 at a time (videos.list allows up to 50 ids
per call, 1 quota unit regardless of batch size -- ingesting a 200-video
channel costs roughly 4 videos.list calls + a handful of playlistItems.list
calls, all 1 unit each).
"""

import re
from dataclasses import dataclass, field

import requests

_BASE = "https://www.googleapis.com/youtube/v3"


class ChannelNotFoundError(ValueError):
    pass


@dataclass
class ChannelInfo:
    channel_id: str
    handle: str
    title: str
    thumbnail_url: str
    uploads_playlist_id: str


@dataclass
class ChannelVideo:
    video_id: str
    title: str
    description: str
    tags: list[str]
    published_at: str
    duration_seconds: int
    view_count: int
    like_count: int
    comment_count: int


_DURATION_PATTERN = re.compile(
    r"PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?"
)


def parse_iso8601_duration(value: str) -> int:
    """YouTube returns duration as ISO 8601 ('PT4M13S'), not seconds. No
    external dependency for this -- the format YouTube actually emits is a
    small, fixed subset (hours/minutes/seconds only, no days/months/years),
    so a regex covers it without pulling in isodate."""
    match = _DURATION_PATTERN.fullmatch(value or "")
    if not match:
        return 0
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    return hours * 3600 + minutes * 60 + seconds


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _normalize_handle(handle_or_url: str) -> str:
    """Accepts '@handle', 'handle', or a full channel/handle URL."""
    value = handle_or_url.strip()
    match = re.search(r"youtube\.com/(@[\w.-]+)", value)
    if match:
        return match.group(1)
    if not value.startswith("@"):
        value = f"@{value}"
    return value


def resolve_channel(handle_or_url: str, api_key: str) -> ChannelInfo:
    handle = _normalize_handle(handle_or_url)
    response = requests.get(
        f"{_BASE}/channels",
        params={"part": "snippet,contentDetails", "forHandle": handle, "key": api_key},
        timeout=10,
    )
    response.raise_for_status()
    items = response.json().get("items", [])
    if not items:
        raise ChannelNotFoundError(f"No channel found for: {handle_or_url}")
    item = items[0]
    snippet = item["snippet"]
    thumbnails = snippet.get("thumbnails", {})
    thumbnail_url = (
        thumbnails.get("high", {}).get("url")
        or thumbnails.get("default", {}).get("url", "")
    )
    return ChannelInfo(
        channel_id=item["id"],
        handle=handle,
        title=snippet.get("title", ""),
        thumbnail_url=thumbnail_url,
        uploads_playlist_id=item["contentDetails"]["relatedPlaylists"]["uploads"],
    )


def _fetch_uploaded_video_ids(uploads_playlist_id: str, api_key: str, max_videos: int = 500) -> list[str]:
    """Pages playlistItems.list (50 per page, 1 quota unit per page) until the
    playlist is exhausted or max_videos is hit -- a hard cap so one very large
    channel can't blow the daily 10,000-unit budget in a single ingest."""
    video_ids: list[str] = []
    page_token = None
    while len(video_ids) < max_videos:
        params = {
            "part": "contentDetails",
            "playlistId": uploads_playlist_id,
            "maxResults": 50,
            "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token
        response = requests.get(f"{_BASE}/playlistItems", params=params, timeout=10)
        response.raise_for_status()
        payload = response.json()
        video_ids.extend(item["contentDetails"]["videoId"] for item in payload.get("items", []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    return video_ids[:max_videos]


def _fetch_video_batch(video_ids: list[str], api_key: str) -> list[ChannelVideo]:
    """videos.list accepts up to 50 comma-separated ids per call."""
    response = requests.get(
        f"{_BASE}/videos",
        params={
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(video_ids),
            "key": api_key,
        },
        timeout=10,
    )
    response.raise_for_status()
    videos = []
    for item in response.json().get("items", []):
        snippet = item["snippet"]
        statistics = item.get("statistics", {})
        content_details = item.get("contentDetails", {})
        videos.append(
            ChannelVideo(
                video_id=item["id"],
                title=snippet.get("title", ""),
                description=snippet.get("description", ""),
                tags=snippet.get("tags", []),
                published_at=snippet.get("publishedAt", ""),
                duration_seconds=parse_iso8601_duration(content_details.get("duration", "")),
                view_count=_as_int(statistics.get("viewCount")),
                like_count=_as_int(statistics.get("likeCount")),
                comment_count=_as_int(statistics.get("commentCount")),
            )
        )
    return videos


def fetch_channel_videos(uploads_playlist_id: str, api_key: str, max_videos: int = 500) -> list[ChannelVideo]:
    video_ids = _fetch_uploaded_video_ids(uploads_playlist_id, api_key, max_videos)
    videos: list[ChannelVideo] = []
    for i in range(0, len(video_ids), 50):
        videos.extend(_fetch_video_batch(video_ids[i : i + 50], api_key))
    return videos
