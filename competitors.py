from collections import Counter
from dataclasses import dataclass, field

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
    competitor_median_views: int
    gap: int
    top_competitors: list[CompetitorVideo]
    missing_tags: list[tuple[str, int]]
    outliers: list[CompetitorVideo] = field(default_factory=list)

    @property
    def has_outliers(self) -> bool:
        """True when the comparison set contains a video so far out of scale
        that presenting the set as "channels like yours" would be false."""
        return bool(self.outliers)


# A competitor this many times above the set's median is a different kind of
# channel, not a peer -- a viral hit or an established brand that happened to
# rank for the same words. Kept in the set (it IS ranking, which is worth
# seeing) but excluded from the summary statistic and marked in the UI.
OUTLIER_VIEW_MULTIPLE = 10

# How many distinct competitors must use a phrase before it may be PRESENTED
# as consensus. Deliberately the same bar as keyword_rank.COMPETITOR_CONSENSUS_MIN
# -- one channel using a phrase is one person's guess in both places, and the
# two surfaces disagreeing about that would be indefensible.
COMPETITOR_AGREEMENT_MIN = 2


def _median(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return round((ordered[middle - 1] + ordered[middle]) / 2)


def split_outliers(
    competitors: list[CompetitorVideo],
) -> tuple[list[CompetitorVideo], list[CompetitorVideo]]:
    """(peers, outliers), split on distance from the set's own median.

    Deliberately relative to the competitor set rather than to the user's own
    view count: a new upload on a large channel has few views, so the user's
    number is a poor stand-in for their channel's authority, and this app
    never fetches subscriber counts (channels.list is extra quota).
    """
    if len(competitors) < 3:
        # Too small a sample for a median to mean anything.
        return list(competitors), []
    median = _median([c.view_count for c in competitors])
    if median <= 0:
        return list(competitors), []
    peers, outliers = [], []
    for competitor in competitors:
        (outliers if competitor.view_count > median * OUTLIER_VIEW_MULTIPLE else peers).append(competitor)
    return peers, outliers


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
    """Tags competitors rank with that this video is missing, ranked by how
    many DISTINCT competitors use each one. Returns (tag, competitor_count).

    This used to rank by combined view count, on the reasoning that a tag on a
    500k-view video is worth more than the same tag on a 5k-view one. Measured
    against a realistic search result, that inverted the output: one unrelated
    4M-view video pushed "study abroad", "germany vlog" and "travel" above
    "aps certificate germany", which two genuinely comparable competitors both
    used. View-weighting ranks the tag by whoever happens to be biggest, which
    measures that channel's audience, not the tag's value to this creator --
    and a small channel cannot inherit a large one's traffic by copying its
    words.

    Counting distinct competitors instead makes this agree with the signal
    keyword_rank already trusts (COMPETITOR_CONSENSUS_MIN): one channel using
    a phrase is one person's guess, several independently converging on it is
    evidence about the niche's vocabulary. Every competitor gets one vote
    regardless of size, which is the entire point.
    """
    own_lower = {t.lower() for t in video_tags}
    consensus = Counter()
    for competitor in competitors:
        # set() so one video repeating a tag cannot manufacture consensus
        # on its own.
        for tag in {t for t in competitor.tags if t.lower() not in own_lower}:
            consensus[tag] += 1
    # Sorted by count, then alphabetically -- Counter.most_common leaves ties
    # in insertion order, which would make the output depend on the order the
    # search API happened to return videos in.
    return sorted(consensus.items(), key=lambda item: (-item[1], item[0]))[:top_k]


def audience_gap(
    user_views: int,
    user_tags: list[str],
    competitors: list[CompetitorVideo],
    top_n: int = GAP_COMPETITOR_COUNT,
) -> AudienceGap | None:
    """How many views the top-ranking rivals are pulling that this video is not.
    None when there are no competitors to compare against.

    Reports the MEDIAN, not the mean. One viral result in a search of five is
    common, and it destroys a mean: measured on a realistic set (4M / 7k / 6k
    views) the mean came out at 1,337,667 and told a creator sitting at 5,000
    views that their addressable gap was 1.3 million. The median reports 7,000
    -- the same set, an achievable target, and a number that describes the
    videos this creator is actually competing with.
    """
    if not competitors:
        return None

    # Search results arrive in relevance order, so the first few are the ones
    # actually ranking for this video's own topic.
    top = competitors[:top_n]
    peers, outliers = split_outliers(top)
    # Outliers are excluded from the headline number but NOT from the tag
    # consensus: they are one vote each there, which is harmless, and dropping
    # them entirely would discard real evidence about the niche's vocabulary.
    median = _median([c.view_count for c in (peers or top)])
    return AudienceGap(
        competitor_median_views=median,
        gap=max(0, median - user_views),
        top_competitors=top,
        missing_tags=steal_tags(user_tags, top),
        outliers=outliers,
    )


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
