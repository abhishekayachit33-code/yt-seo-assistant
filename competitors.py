from dataclasses import dataclass

import requests

_SEARCH_ENDPOINT = "https://www.googleapis.com/youtube/v3/search"
_VIDEOS_ENDPOINT = "https://www.googleapis.com/youtube/v3/videos"


@dataclass
class CompetitorVideo:
    video_id: str
    title: str
    channel_title: str
    tags: list[str]


def find_competitors(title: str, api_key: str, exclude_video_id: str, max_results: int = 5) -> list[CompetitorVideo]:
    """search.list costs 100 quota units -- caller must make this opt-in.
    Returns [] on any error rather than raising, since this is a nice-to-have,
    not core analysis."""
    try:
        search_response = requests.get(
            _SEARCH_ENDPOINT,
            params={
                "part": "snippet",
                "q": title,
                "type": "video",
                "maxResults": max_results + 1,  # +1 in case the video itself appears
                "key": api_key,
            },
            timeout=10,
        )
        search_response.raise_for_status()
    except requests.exceptions.HTTPError:
        return []

    video_ids = [
        item["id"]["videoId"]
        for item in search_response.json().get("items", [])
        if item["id"]["videoId"] != exclude_video_id
    ][:max_results]

    if not video_ids:
        return []

    try:
        videos_response = requests.get(
            _VIDEOS_ENDPOINT,
            params={"part": "snippet", "id": ",".join(video_ids), "key": api_key},
            timeout=10,
        )
        videos_response.raise_for_status()
    except requests.exceptions.HTTPError:
        return []

    return [
        CompetitorVideo(
            video_id=item["id"],
            title=item["snippet"].get("title", ""),
            channel_title=item["snippet"].get("channelTitle", ""),
            tags=item["snippet"].get("tags", []),
        )
        for item in videos_response.json().get("items", [])
    ]
