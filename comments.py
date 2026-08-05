import requests

_ENDPOINT = "https://www.googleapis.com/youtube/v3/commentThreads"


def fetch_top_comments(video_id: str, api_key: str, max_results: int = 50) -> list[str]:
    """Top-level comment text, ranked by relevance. Empty list if comments are
    disabled or unavailable -- never raises for that case, same pattern as
    fetch_transcript_text()."""
    try:
        response = requests.get(
            _ENDPOINT,
            params={
                "part": "snippet",
                "videoId": video_id,
                "order": "relevance",
                "maxResults": max_results,
                "textFormat": "plainText",
                "key": api_key,
            },
            timeout=10,
        )
        response.raise_for_status()
    except requests.exceptions.HTTPError:
        return []

    items = response.json().get("items", [])
    return [
        item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
        for item in items
    ]
