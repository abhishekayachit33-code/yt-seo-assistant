from competitors import CompetitorVideo, audience_gap
from cta import analyze_ctas
from limits import compute_health_score
from playbook import build_playbook
from shelf_life import classify
from transcript import TranscriptSegment


def competitor(views: int, tags: list[str]) -> CompetitorVideo:
    return CompetitorVideo(video_id="c", title="c", channel_title="c", tags=tags, view_count=views)


def video(lines, total=600.0):
    segs = [TranscriptSegment(start=t, duration=3.0, text=x) for t, x in lines]
    segs.append(TranscriptSegment(start=total - 3, duration=3.0, text="bye"))
    return segs


def test_no_signals_produces_no_actions():
    _, rules = compute_health_score(
        "short", "x" * 300 + " https://instagram.com/me", ["a"] * 40, [f"#{i}" for i in range(12)]
    )
    actions = build_playbook(rules)
    assert actions == []


def test_missing_health_rule_becomes_an_action():
    _, rules = compute_health_score("x" * 200, "", [], [])
    actions = build_playbook(rules)
    titles = [a.title for a in actions]
    assert any("Title" in t for t in titles)
    assert any("Description" in t for t in titles)


def test_audience_gap_produces_the_highest_priority_action():
    gap = audience_gap(1000, [], [competitor(500_000, ["streamlit deployment"])])
    _, rules = compute_health_score(
        "short", "x" * 300 + " https://instagram.com/me", ["a"] * 40, [f"#{i}" for i in range(12)]
    )
    actions = build_playbook(rules, gap=gap)
    assert actions[0].title.startswith("Add")
    assert "streamlit deployment" in actions[0].detail
    assert "500,000" in actions[0].detail


def test_stranded_cta_becomes_an_action():
    report = analyze_ctas(video([(570, "please subscribe")], total=600))
    _, rules = compute_health_score(
        "short", "x" * 300 + " https://instagram.com/me", ["a"] * 40, [f"#{i}" for i in range(12)]
    )
    actions = build_playbook(rules, cta_report=report)
    assert any("subscribe" in a.title.lower() for a in actions)
    assert any("09:30" in a.detail for a in actions)


def test_no_cta_at_all_is_flagged():
    report = analyze_ctas(video([(100, "today we bake bread")], total=600))
    _, rules = compute_health_score(
        "short", "x" * 300 + " https://instagram.com/me", ["a"] * 40, [f"#{i}" for i in range(12)]
    )
    actions = build_playbook(rules, cta_report=report)
    assert any("Add a call to action" in a.title for a in actions)


def test_well_placed_cta_produces_no_cta_action():
    report = analyze_ctas(video([(300, "subscribe now")], total=600))
    _, rules = compute_health_score(
        "short", "x" * 300 + " https://instagram.com/me", ["a"] * 40, [f"#{i}" for i in range(12)]
    )
    actions = build_playbook(rules, cta_report=report)
    assert not any("call to action" in a.title.lower() or "subscribe" in a.title.lower() for a in actions)


def test_weak_thumbnail_becomes_an_action():
    _, rules = compute_health_score(
        "short", "x" * 300 + " https://instagram.com/me", ["a"] * 40, [f"#{i}" for i in range(12)]
    )
    review = {"legible_at_small_size": False, "has_clear_focal_point": True, "stands_out_in_feed": True}
    actions = build_playbook(rules, thumbnail_review=review)
    thumb_action = next(a for a in actions if "thumbnail" in a.title.lower())
    assert "legible" in thumb_action.detail


def test_strong_thumbnail_produces_no_action():
    _, rules = compute_health_score(
        "short", "x" * 300 + " https://instagram.com/me", ["a"] * 40, [f"#{i}" for i in range(12)]
    )
    review = {"legible_at_small_size": True, "has_clear_focal_point": True, "stands_out_in_feed": True}
    actions = build_playbook(rules, thumbnail_review=review)
    assert not any("thumbnail" in a.title.lower() for a in actions)


def test_trending_shelf_life_becomes_an_action():
    shelf = classify("Breaking 2026 news today", ["news"], None)
    _, rules = compute_health_score(
        "short", "x" * 300 + " https://instagram.com/me", ["a"] * 40, [f"#{i}" for i in range(12)]
    )
    actions = build_playbook(rules, shelf=shelf)
    assert any("shelf life" in a.title.lower() for a in actions)


def test_evergreen_shelf_life_produces_no_action():
    shelf = classify("How to bake bread: a beginner tutorial", ["tutorial"], None)
    _, rules = compute_health_score(
        "short", "x" * 300 + " https://instagram.com/me", ["a"] * 40, [f"#{i}" for i in range(12)]
    )
    actions = build_playbook(rules, shelf=shelf)
    assert not any("shelf life" in a.title.lower() for a in actions)
