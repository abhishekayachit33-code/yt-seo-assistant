from datetime import datetime, timedelta, timezone

from analytics import (
    days_since_upload,
    project_views,
    summarize_performance,
    uplift_range,
)

NOW = datetime(2026, 8, 5, tzinfo=timezone.utc)


def test_days_since_upload_counts_whole_days():
    published = (NOW - timedelta(days=10)).isoformat().replace("+00:00", "Z")
    assert days_since_upload(published, now=NOW) == 10


def test_days_since_upload_floors_at_one_for_today():
    published = NOW.isoformat().replace("+00:00", "Z")
    assert days_since_upload(published, now=NOW) == 1


def test_days_since_upload_handles_missing_or_bad_timestamp():
    assert days_since_upload("", now=NOW) == 1
    assert days_since_upload("not a date", now=NOW) == 1


def test_velocity_and_engagement_rate():
    published = (NOW - timedelta(days=10)).isoformat().replace("+00:00", "Z")
    perf = summarize_performance(1000, 80, 20, published, now=NOW)
    assert perf.views_per_day == 100
    assert perf.engagement_rate == 10.0


def test_engagement_rate_is_zero_when_no_views():
    perf = summarize_performance(0, 0, 0, "", now=NOW)
    assert perf.engagement_rate == 0.0
    assert perf.views_per_day == 0


def test_uplift_bands_match_published_thresholds():
    assert uplift_range(40) == (0.25, 0.50)
    assert uplift_range(55) == (0.25, 0.50)
    assert uplift_range(20) == (0.10, 0.25)
    assert uplift_range(10) == (0.05, 0.10)
    assert uplift_range(1) == (0.00, 0.05)


def test_no_score_improvement_projects_no_uplift():
    assert uplift_range(0) == (0.0, 0.0)
    assert uplift_range(-30) == (0.0, 0.0)


def test_projection_applies_uplift_to_baseline_only():
    # 100 views/day over 30 days = 3000 baseline on top of 5000 existing views.
    projection = project_views(5000, 100, score_delta=40, days=30)
    assert projection.baseline_views == 8000
    assert projection.low_views == 5000 + round(3000 * 1.25)
    assert projection.high_views == 5000 + round(3000 * 1.50)


def test_flat_score_projects_baseline_on_both_ends():
    projection = project_views(5000, 100, score_delta=0, days=30)
    assert projection.low_views == projection.high_views == projection.baseline_views
