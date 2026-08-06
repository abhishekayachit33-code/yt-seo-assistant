from collections import Counter
from dataclasses import dataclass

import requests

_SEARCH_ENDPOINT = "https://www.googleapis.com/youtube/v3/search"
_VIDEOS_ENDPOINT = "https://www.googleapis.com/youtube/v3/videos"


GAP_COMPETITOR_COUNT = 3


@dataclass
class CompetitorVideo:
    video_id: str
    title: str
    channel_title: str
    tags: list[str]
    view_count: int = 0


@dataclass
class AudienceGap:
    competitor_average_views: int
    gap: int
    top_competitors: list[CompetitorVideo]
    missing_tags: list[tuple[str, int]]


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
        # 'statistics' rides along on the snippet request -- videos.list is
        # 1 quota unit regardless of how many parts are requested.
        videos_response = requests.get(
            _VIDEOS_ENDPOINT,
            params={"part": "snippet,statistics", "id": ",".join(video_ids), "key": api_key},
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
            view_count=_as_int(item.get("statistics", {}).get("viewCount")),
        )
        for item in videos_response.json().get("items", [])
    ]


def steal_tags(
    video_tags: list[str], competitors: list[CompetitorVideo], top_k: int = 8
) -> list[tuple[str, int]]:
    """Tags competitors rank with that this video is missing, weighted by the
    views behind them. A tag on a 500k-view video is worth more than the same
    tag on a 5k-view video, so ranking by combined views surfaces the keywords
    actually carrying traffic rather than the ones that merely appear often."""
    own_lower = {t.lower() for t in video_tags}
    weighted = Counter()
    for c in competitors:
        for t in c.tags:
            if t.lower() not in own_lower:
                weighted[t] += max(c.view_count, 1)
    return weighted.most_common(top_k)


def audience_gap(
    user_views: int,
    user_tags: list[str],
    competitors: list[CompetitorVideo],
    top_n: int = GAP_COMPETITOR_COUNT,
) -> AudienceGap | None:
    """How many views the top-ranking rivals are pulling that this video is not.
    None when there are no competitors to compare against."""
    if not competitors:
        return None

    # Search results arrive in relevance order, so the first few are the ones
    # actually ranking for this video's own topic.
    top = competitors[:top_n]
    average = round(sum(c.view_count for c in top) / len(top))
    return AudienceGap(
        competitor_average_views=average,
        gap=max(0, average - user_views),
        top_competitors=top,
        missing_tags=steal_tags(user_tags, top),
    )


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
