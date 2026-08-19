"""Tests for the harness logic in eval_relevance_floor.py itself -- not for
its live results, which depend on a real channel's data and a network call.
The point here is that the circularity control and the CSV parser cannot be
silently wrong, since a bug in either would make the eval's numbers meaningless
regardless of how real the underlying data is.
"""

import csv
import io

from eval_relevance_floor import appears_in_title, evaluate, load_search_terms


# --------------------------------------------------------- circularity control


def test_term_already_in_title_is_trivial():
    assert appears_in_title("mba in dubai", "Top MBA Universities in Dubai")


def test_term_absent_from_title_is_not_trivial():
    assert not appears_in_title("wollongong university dubai", "Top Australian Universities in Dubai")


def test_plural_and_singular_still_count_as_the_same_word():
    """Without stemming, "university"/"universities" would false-negative
    into EARNED, overstating what the pipeline actually found."""
    assert appears_in_title("birmingham university", "Birmingham Universities Guide")


def test_word_order_does_not_defeat_the_match():
    assert appears_in_title("dubai mba", "MBA Programs in Dubai")


def test_partial_overlap_is_not_trivial():
    """Only some of the term's words appearing must not count -- that would
    let a loosely-related title claim credit for a term it does not cover."""
    assert not appears_in_title("mba scholarship deadline", "MBA Programs in Dubai")


def test_empty_term_is_never_trivial():
    assert not appears_in_title("", "Any Title At All")


# -------------------------------------------------------------------- parsing


def _write_csv(rows: list[dict], path: str) -> None:
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "Traffic source", "Source type", "Source title", "Views",
            "Watch time (hours)", "Average view duration",
        ])
        writer.writeheader()
        writer.writerows(rows)


def test_load_search_terms_keeps_only_yt_search_rows(tmp_path):
    path = tmp_path / "table.csv"
    _write_csv([
        {"Traffic source": "Total", "Source title": "", "Views": "13312"},
        {"Traffic source": "YT_SEARCH.mba in dubai", "Source title": "mba in dubai", "Views": "189"},
        {"Traffic source": "Suggested videos", "Source title": "", "Views": "4396"},
    ], path)
    terms = load_search_terms(str(path))
    assert terms == [("mba in dubai", 189)]


def test_load_search_terms_sorts_by_views_descending(tmp_path):
    path = tmp_path / "table.csv"
    _write_csv([
        {"Traffic source": "YT_SEARCH.a", "Source title": "a", "Views": "5"},
        {"Traffic source": "YT_SEARCH.b", "Source title": "b", "Views": "50"},
    ], path)
    assert [t for t, _ in load_search_terms(str(path))] == ["b", "a"]


def test_load_search_terms_missing_file_raises_with_guidance():
    import pytest
    with pytest.raises(SystemExit, match="Export it from YouTube Studio"):
        load_search_terms("/nonexistent/path.csv")


# ------------------------------------------------------------------- scoring


def test_evaluate_splits_trivial_from_earned():
    videos = [{"video_id": "v1", "title": "MBA in Dubai Guide", "description": ""}]
    terms = [("mba in dubai", 100), ("wollongong dubai", 50)]
    result = evaluate(terms, videos, floor=0.2)
    assert [r["term"] for r in result["trivial"]] == ["mba in dubai"]
    assert [r["term"] for r in result["earned"]] == ["wollongong dubai"]


def test_evaluate_marks_survival_against_the_given_floor():
    videos = [{"video_id": "v1", "title": "Totally Unrelated Topic", "description": ""}]
    terms = [("completely different subject entirely", 10)]
    low = evaluate(terms, videos, floor=0.0)
    high = evaluate(terms, videos, floor=0.99)
    assert low["earned"][0]["survives"] is True
    assert high["earned"][0]["survives"] is False


def test_evaluate_picks_the_best_matching_video_not_the_first():
    videos = [
        {"video_id": "v1", "title": "Unrelated Cooking Tips", "description": ""},
        {"video_id": "v2", "title": "MBA in Dubai Complete Guide", "description": ""},
    ]
    result = evaluate([("mba dubai", 10)], videos, floor=0.0)
    assert result["trivial"][0]["video_title"] == "MBA in Dubai Complete Guide"
