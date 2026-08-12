"""Cross-video channel analysis -- pure Python over data already ingested by
channel.py, no I/O and no LLM call. Everything here answers a question a
single-video tool structurally cannot: how does this channel's own history
predict what works, not what SEO best-practice generally says.

Every report degrades gracefully on small channels rather than emitting
statistically meaningless output -- each function has its own minimum sample
size below which it returns an empty list instead of a report built on 3
videos.
"""

import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from channel import ChannelVideo
from limits import compute_health_score, extract_hashtags

MIN_SAMPLE_FOR_FEATURE = 4   # need at least this many videos on each side (with/without)
MIN_CLUSTER_SIZE = 2
MIN_VIDEOS_FOR_OUTLIERS = 5
MIN_VIDEOS_FOR_DURATION = 5
MIN_VIDEOS_FOR_CADENCE = 3
REFRESH_MIN_AGE_DAYS = 60
REFRESH_HEALTH_CEILING = 80

_STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "your", "you", "how", "what",
    "why", "when", "from", "into", "about", "have", "just", "will", "can",
    "are", "was", "were", "but", "not", "all", "new", "get", "our", "out",
    "video", "episode", "part",
}


def _parsed_date(published_at: str) -> datetime | None:
    if not published_at:
        return None
    try:
        return datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return None


def views_per_day(video: ChannelVideo, now: datetime | None = None) -> float:
    published = _parsed_date(video.published_at)
    if published is None:
        return 0.0
    now = now or datetime.now(timezone.utc)
    days = max((now - published).days, 1)
    return video.view_count / days


@dataclass
class TitleFeatureStat:
    label: str
    with_median: float
    without_median: float
    lift: float  # with_median / without_median, 1.0 = no effect
    with_count: int
    without_count: int


def _has_number(title: str) -> bool:
    return bool(re.search(r"\d", title))


def _is_question(title: str) -> bool:
    return title.strip().endswith("?")


def _has_how_to(title: str) -> bool:
    return "how to" in title.lower()


def _has_bracket_tag(title: str) -> bool:
    return bool(re.search(r"[\[\(].+?[\]\)]", title))


def _has_all_caps_word(title: str) -> bool:
    return any(len(w) >= 3 and w.isupper() for w in re.findall(r"[A-Za-z']+", title))


def _is_short_title(title: str) -> bool:
    return len(title) < 60


_TITLE_FEATURES = [
    ("Has a number", _has_number),
    ("Phrased as a question", _is_question),
    ('"How to" phrasing', _has_how_to),
    ("Has a bracket/parenthetical tag", _has_bracket_tag),
    ("Has an ALL-CAPS word", _has_all_caps_word),
    ("Under 60 characters", _is_short_title),
]


def title_feature_report(videos: list[ChannelVideo], now: datetime | None = None) -> list[TitleFeatureStat]:
    """For each title feature, compares median views/day of videos that have
    it vs. videos that don't -- on THIS channel's own history, not a generic
    best-practice list. Skips a feature entirely if either side has too few
    videos to mean anything."""
    now = now or datetime.now(timezone.utc)
    vpd = {v.video_id: views_per_day(v, now) for v in videos}

    stats = []
    for label, predicate in _TITLE_FEATURES:
        with_vals = [vpd[v.video_id] for v in videos if predicate(v.title)]
        without_vals = [vpd[v.video_id] for v in videos if not predicate(v.title)]
        if len(with_vals) < MIN_SAMPLE_FOR_FEATURE or len(without_vals) < MIN_SAMPLE_FOR_FEATURE:
            continue
        with_median = statistics.median(with_vals)
        without_median = statistics.median(without_vals)
        lift = with_median / without_median if without_median > 0 else 0.0
        stats.append(TitleFeatureStat(
            label=label,
            with_median=with_median,
            without_median=without_median,
            lift=lift,
            with_count=len(with_vals),
            without_count=len(without_vals),
        ))
    stats.sort(key=lambda s: s.lift, reverse=True)
    return stats


@dataclass
class TopicCluster:
    keyword: str
    video_count: int
    median_views_per_day: float
    example_titles: list[str]


def _title_keywords(title: str) -> list[str]:
    words = re.findall(r"[A-Za-z']+", title.lower())
    return [w for w in words if len(w) >= 4 and w not in _STOPWORDS]


def topic_clusters(videos: list[ChannelVideo], now: datetime | None = None) -> list[TopicCluster]:
    """Groups videos by their most channel-distinctive title keyword (the
    highest-frequency non-stopword across the whole channel that also
    appears in that video's title), then ranks the resulting clusters by
    median views/day. Deliberately simple word-bucket grouping, not a real
    embedding-based clustering model -- cheap, dependency-free, and good
    enough to answer 'which of my recurring topics actually performs'."""
    now = now or datetime.now(timezone.utc)
    vpd = {v.video_id: views_per_day(v, now) for v in videos}

    corpus_freq = Counter()
    video_keywords = {}
    for v in videos:
        kws = _title_keywords(v.title)
        video_keywords[v.video_id] = kws
        corpus_freq.update(set(kws))

    clusters: dict[str, list[ChannelVideo]] = defaultdict(list)
    for v in videos:
        kws = video_keywords[v.video_id]
        if not kws:
            continue
        dominant = max(kws, key=lambda w: corpus_freq[w])
        clusters[dominant].append(v)

    result = []
    for keyword, members in clusters.items():
        if len(members) < MIN_CLUSTER_SIZE:
            continue
        median = statistics.median(vpd[v.video_id] for v in members)
        result.append(TopicCluster(
            keyword=keyword,
            video_count=len(members),
            median_views_per_day=median,
            example_titles=[v.title for v in members[:3]],
        ))
    result.sort(key=lambda c: c.median_views_per_day, reverse=True)
    return result


@dataclass
class OutlierVideo:
    video: ChannelVideo
    views_per_day: float
    ratio_to_median: float


def find_outliers(
    videos: list[ChannelVideo], now: datetime | None = None
) -> tuple[list[OutlierVideo], list[OutlierVideo]]:
    """Over/under-performers relative to this channel's own median views/day.
    Over-performers are the template to repeat; under-performers are the
    diagnostic set for what isn't working. Needs a minimum channel size or
    'the median' isn't a meaningful yardstick."""
    if len(videos) < MIN_VIDEOS_FOR_OUTLIERS:
        return [], []
    now = now or datetime.now(timezone.utc)
    vpd = {v.video_id: views_per_day(v, now) for v in videos}
    median = statistics.median(vpd.values())
    if median <= 0:
        return [], []

    over, under = [], []
    for v in videos:
        ratio = vpd[v.video_id] / median
        entry = OutlierVideo(video=v, views_per_day=vpd[v.video_id], ratio_to_median=ratio)
        if ratio >= 2.0:
            over.append(entry)
        elif ratio <= 0.5:
            under.append(entry)
    over.sort(key=lambda e: e.ratio_to_median, reverse=True)
    under.sort(key=lambda e: e.ratio_to_median)
    return over, under


@dataclass
class DurationBucketStat:
    label: str
    video_count: int
    median_views_per_day: float


_DURATION_BUCKETS = [
    ("Under 5 min", 0, 300),
    ("5-10 min", 300, 600),
    ("10-20 min", 600, 1200),
    ("20-40 min", 1200, 2400),
    ("40+ min", 2400, float("inf")),
]


def duration_sweet_spot(videos: list[ChannelVideo], now: datetime | None = None) -> list[DurationBucketStat]:
    if len(videos) < MIN_VIDEOS_FOR_DURATION:
        return []
    now = now or datetime.now(timezone.utc)
    vpd = {v.video_id: views_per_day(v, now) for v in videos}

    stats = []
    for label, low, high in _DURATION_BUCKETS:
        members = [v for v in videos if low <= v.duration_seconds < high]
        if not members:
            continue
        stats.append(DurationBucketStat(
            label=label,
            video_count=len(members),
            median_views_per_day=statistics.median(vpd[v.video_id] for v in members),
        ))
    stats.sort(key=lambda s: s.median_views_per_day, reverse=True)
    return stats


@dataclass
class CadenceReport:
    median_gap_days: float
    most_common_weekday: str
    consistency_stddev_days: float


_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def cadence_report(videos: list[ChannelVideo]) -> CadenceReport | None:
    dates = sorted(d for d in (_parsed_date(v.published_at) for v in videos) if d is not None)
    if len(dates) < MIN_VIDEOS_FOR_CADENCE:
        return None
    gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
    weekday_counts = Counter(d.weekday() for d in dates)
    most_common = weekday_counts.most_common(1)[0][0]
    return CadenceReport(
        median_gap_days=statistics.median(gaps),
        most_common_weekday=_WEEKDAYS[most_common],
        consistency_stddev_days=statistics.pstdev(gaps) if len(gaps) > 1 else 0.0,
    )


@dataclass
class RefreshCandidate:
    video: ChannelVideo
    views_per_day: float
    health_score: int
    reason: str


def refresh_queue(videos: list[ChannelVideo], now: datetime | None = None, limit: int = 10) -> list[RefreshCandidate]:
    """Old videos that are still pulling meaningful traffic but have weak
    metadata -- the highest-ROI place to spend five minutes, since the
    audience is already there and the fix is free (no new content needed).
    Ranked by views/day among videos below the health-score ceiling."""
    now = now or datetime.now(timezone.utc)
    vpd = {v.video_id: views_per_day(v, now) for v in videos}
    if not vpd:
        return []
    median_vpd = statistics.median(vpd.values())
    if median_vpd <= 0:
        return []

    candidates = []
    for v in videos:
        published = _parsed_date(v.published_at)
        if published is None or (now - published).days < REFRESH_MIN_AGE_DAYS:
            continue
        if vpd[v.video_id] < median_vpd * 0.25:
            continue  # not enough residual traffic to be worth touching
        hashtags = extract_hashtags(v.description)
        score, _rules = compute_health_score(v.title, v.description, v.tags, hashtags)
        if score >= REFRESH_HEALTH_CEILING:
            continue
        candidates.append(RefreshCandidate(
            video=v,
            views_per_day=vpd[v.video_id],
            health_score=score,
            reason=f"{score}% metadata health, still earning {vpd[v.video_id]:.0f} views/day",
        ))
    candidates.sort(key=lambda c: c.views_per_day, reverse=True)
    return candidates[:limit]
