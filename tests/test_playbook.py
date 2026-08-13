from competitors import CompetitorVideo, audience_gap
from cta import analyze_ctas
from keywords import estimate_spoken_length
from limits import compute_health_score
from playbook import NEEDS_WORK, READY, UNKNOWN, build_playbook, build_preproduction_checklist
from shelf_life import classify
from transcript import TranscriptSegment


def competitor(views: int, tags: list[str]) -> CompetitorVideo:
    return CompetitorVideo(video_id="c", title="c", channel_title="c", tags=tags, view_count=views)


def video(lines, total=600.0):
    segs = [TranscriptSegment(start=t, duration=3.0, text=x) for t, x in lines]
    segs.append(TranscriptSegment(start=total - 3, duration=3.0, text="bye"))
    return segs


def test_no_signals_produces_no_actions():
    # 4 hashtags: within the real recommended range (3-5) -- 12 used to pass
    # here too, back when the health rule wrongly targeted 10-15.
    _, rules = compute_health_score(
        "short", "x" * 300 + " https://instagram.com/me", ["a"] * 40, [f"#{i}" for i in range(4)]
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


def _shelf():
    return classify("How to bake bread: a beginner tutorial", ["tutorial"], None)


def test_checklist_all_missing_data_is_unknown_not_needs_work():
    checklist = build_preproduction_checklist(90, {"verdict": "unavailable"}, None, None)
    statuses = {item.label: item.status for item in checklist.items}
    assert statuses["Hook strength"] == UNKNOWN
    assert statuses["Estimated length"] == UNKNOWN
    assert statuses["Shelf-life framing"] == UNKNOWN
    assert checklist.ready_to_record  # unknown never blocks readiness


def test_checklist_strong_hook_and_high_score_is_ready():
    speech = estimate_spoken_length(" ".join(["word"] * 1000))
    checklist = build_preproduction_checklist(
        90, {"verdict": "strong, hooks immediately"}, speech, _shelf()
    )
    statuses = {item.label: item.status for item in checklist.items}
    assert statuses["Hook strength"] == READY
    assert statuses["Metadata health"] == READY
    assert statuses["Estimated length"] == READY
    assert checklist.ready_to_record


def test_checklist_weak_hook_flagged_needs_work():
    checklist = build_preproduction_checklist(90, {"verdict": "weak, doesn't hook fast enough"}, None, None)
    hook_item = next(i for i in checklist.items if i.label == "Hook strength")
    assert hook_item.status == NEEDS_WORK
    assert not checklist.ready_to_record


def test_checklist_low_health_score_flagged_needs_work():
    checklist = build_preproduction_checklist(40, {"verdict": "unavailable"}, None, None)
    health_item = next(i for i in checklist.items if i.label == "Metadata health")
    assert health_item.status == NEEDS_WORK
    assert not checklist.ready_to_record


def test_checklist_very_short_length_flagged():
    speech = estimate_spoken_length("one two three four five")
    checklist = build_preproduction_checklist(90, {"verdict": "unavailable"}, speech, None)
    length_item = next(i for i in checklist.items if i.label == "Estimated length")
    assert length_item.status == NEEDS_WORK


def test_checklist_very_long_length_flagged():
    speech = estimate_spoken_length(" ".join(["word"] * 6000))  # ~43 min at 140 wpm
    checklist = build_preproduction_checklist(90, {"verdict": "unavailable"}, speech, None)
    length_item = next(i for i in checklist.items if i.label == "Estimated length")
    assert length_item.status == NEEDS_WORK


def test_checklist_shelf_life_is_informational_never_blocks():
    trending = classify("Breaking 2026 news today", ["news"], None)
    checklist = build_preproduction_checklist(90, {"verdict": "unavailable"}, None, trending)
    shelf_item = next(i for i in checklist.items if i.label == "Shelf-life framing")
    assert shelf_item.status == READY  # informational, not a blocker
    assert checklist.ready_to_record
