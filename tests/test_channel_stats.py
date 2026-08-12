from datetime import datetime, timedelta, timezone

from channel import ChannelVideo
from channel_stats import (
    cadence_report, duration_sweet_spot, find_outliers, refresh_queue,
    title_feature_report, topic_clusters, views_per_day,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _video(video_id, title, days_ago, views, duration_seconds=600, tags=None, description="x" * 250):
    published = NOW - timedelta(days=days_ago)
    return ChannelVideo(
        video_id=video_id,
        title=title,
        description=description,
        tags=tags or [f"tag{i}" for i in range(35)],
        published_at=published.isoformat(),
        duration_seconds=duration_seconds,
        view_count=views,
        like_count=0,
        comment_count=0,
    )


def test_views_per_day_divides_by_age():
    v = _video("a", "Title", days_ago=10, views=1000)
    assert views_per_day(v, NOW) == 100.0


def test_views_per_day_floors_age_at_one_day():
    v = _video("a", "Title", days_ago=0, views=500)
    assert views_per_day(v, NOW) == 500.0


def test_title_feature_report_needs_minimum_sample_on_both_sides():
    # Only 2 videos with a number -- below MIN_SAMPLE_FOR_FEATURE (4), so the
    # feature must not be reported at all.
    videos = [_video(str(i), f"Video {i}" if i < 2 else "No digits here", 30, 100) for i in range(6)]
    report = title_feature_report(videos, NOW)
    assert not any(s.label == "Has a number" for s in report)


def test_title_feature_report_detects_real_lift():
    with_number = [_video(f"n{i}", f"Top {i} Tips", 30, 1000) for i in range(5)]
    without_number = [_video(f"w{i}", "General thoughts on stuff", 30, 100) for i in range(5)]
    report = title_feature_report(with_number + without_number, NOW)
    stat = next(s for s in report if s.label == "Has a number")
    assert stat.lift == 10.0
    assert stat.with_count == 5
    assert stat.without_count == 5


def test_topic_clusters_groups_by_shared_keyword():
    videos = [
        _video("a", "Docker tutorial for beginners", 30, 1000),
        _video("b", "Advanced Docker networking", 30, 2000),
        _video("c", "My vacation vlog", 30, 50),
    ]
    clusters = topic_clusters(videos, NOW)
    docker_cluster = next(c for c in clusters if c.keyword == "docker")
    assert docker_cluster.video_count == 2


def test_find_outliers_needs_minimum_channel_size():
    videos = [_video(str(i), f"Video {i}", 30, 100) for i in range(3)]
    over, under = find_outliers(videos, NOW)
    assert over == []
    assert under == []


def test_find_outliers_flags_above_and_below_median():
    videos = [_video(str(i), f"Video {i}", 30, 300) for i in range(5)]
    videos.append(_video("hit", "Viral one", 30, 5000))
    videos.append(_video("flop", "Nobody watched", 30, 10))
    over, under = find_outliers(videos, NOW)
    assert any(e.video.video_id == "hit" for e in over)
    assert any(e.video.video_id == "flop" for e in under)


def test_duration_sweet_spot_buckets_by_length():
    videos = [_video(str(i), f"Video {i}", 30, 1000, duration_seconds=200) for i in range(5)]
    videos += [_video(f"l{i}", f"Long {i}", 30, 100, duration_seconds=1800) for i in range(5)]
    stats = duration_sweet_spot(videos, NOW)
    labels = {s.label for s in stats}
    assert "Under 5 min" in labels
    assert "20-40 min" in labels
    short = next(s for s in stats if s.label == "Under 5 min")
    assert short.median_views_per_day > next(s for s in stats if s.label == "20-40 min").median_views_per_day


def test_cadence_report_needs_minimum_history():
    videos = [_video("a", "A", 10, 100), _video("b", "B", 5, 100)]
    assert cadence_report(videos) is None


def test_cadence_report_computes_median_gap():
    videos = [_video(str(i), f"V{i}", days_ago=30 * i, views=100) for i in range(4)]
    report = cadence_report(videos)
    assert report is not None
    assert report.median_gap_days == 30


def test_refresh_queue_skips_recent_videos():
    recent = _video("recent", "Recent", 10, 5000, tags=[])
    videos = [_video(str(i), f"V{i}", 200, 300) for i in range(5)] + [recent]
    candidates = refresh_queue(videos, NOW)
    assert all(c.video.video_id != "recent" for c in candidates)


def test_refresh_queue_skips_healthy_metadata():
    healthy = _video(
        "healthy", "Great Title", 200, 5000,
        description="x" * 300 + " twitter.com/me #a #b #c #d #e #f #g #h #i #j",
        tags=[f"tag{i}" for i in range(35)],
    )
    videos = [_video(str(i), f"V{i}", 200, 300) for i in range(5)] + [healthy]
    candidates = refresh_queue(videos, NOW)
    assert all(c.video.video_id != "healthy" for c in candidates)


def test_refresh_queue_flags_old_earning_weak_metadata():
    weak = _video("weak", "bad", 200, 5000, tags=[], description="short")
    videos = [_video(str(i), f"V{i}", 200, 300) for i in range(5)] + [weak]
    candidates = refresh_queue(videos, NOW)
    assert any(c.video.video_id == "weak" for c in candidates)
