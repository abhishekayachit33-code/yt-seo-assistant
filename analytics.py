"""Performance snapshot and projected reach uplift.

The projection is a transparent heuristic, not a prediction: it maps how far the
metadata compliance score moved to a published band of organic-search uplift,
then applies that band to the video's own observed view velocity. No model is
asked to guess a view count, and every number here is reproducible from the
inputs.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

PROJECTION_DAYS = 30

# (minimum score delta, low uplift, high uplift). Checked highest-first.
UPLIFT_BANDS = [
    (40, 0.25, 0.50),
    (20, 0.10, 0.25),
    (10, 0.05, 0.10),
    (1, 0.00, 0.05),
]


@dataclass
class Performance:
    views: int
    likes: int
    comments: int
    days_since_upload: int
    views_per_day: float
    engagement_rate: float


@dataclass
class Projection:
    score_delta: int
    low_uplift: float
    high_uplift: float
    baseline_views: int
    low_views: int
    high_views: int


def days_since_upload(published_at: str, now: datetime | None = None) -> int:
    """Whole days since publication, floored at 1 so a video uploaded today
    still has a usable per-day denominator."""
    if not published_at:
        return 1
    try:
        published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return 1
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return max(1, (now - published).days)


def summarize_performance(
    views: int, likes: int, comments: int, published_at: str, now: datetime | None = None
) -> Performance:
    days = days_since_upload(published_at, now)
    return Performance(
        views=views,
        likes=likes,
        comments=comments,
        days_since_upload=days,
        views_per_day=views / days,
        # Creators can hide likes; engagement then reflects comments alone
        # rather than being unavailable outright.
        engagement_rate=((likes + comments) / views * 100) if views else 0.0,
    )


def uplift_range(score_delta: int) -> tuple[float, float]:
    """Organic-search uplift band for a given metadata score improvement.
    A score that did not improve projects no uplift."""
    for threshold, low, high in UPLIFT_BANDS:
        if score_delta >= threshold:
            return low, high
    return 0.0, 0.0


def project_views(
    current_views: int, views_per_day: float, score_delta: int, days: int = PROJECTION_DAYS
) -> Projection:
    """Where the video lands in `days` at its current pace, versus that same
    pace lifted by the uplift band the score delta earns."""
    low, high = uplift_range(score_delta)
    baseline = views_per_day * days
    return Projection(
        score_delta=score_delta,
        low_uplift=low,
        high_uplift=high,
        baseline_views=round(current_views + baseline),
        low_views=round(current_views + baseline * (1 + low)),
        high_views=round(current_views + baseline * (1 + high)),
    )
