from shelf_life import classify


def test_tutorial_title_reads_evergreen():
    result = classify("How to deploy Streamlit: a beginner tutorial", ["guide"], None)
    assert result.evergreen_score >= 75
    assert result.classification == "Evergreen"
    assert "24+ months" in result.expectation


def test_dated_news_title_reads_trending():
    result = classify("Breaking: the latest 2026 update, announced today", ["news"], None)
    assert result.evergreen_score <= 25
    assert result.classification == "Trending"


def test_no_signals_stays_neutral_and_unclassified():
    result = classify("My cat", ["cat"], "just some words")
    assert result.evergreen_score == 50
    assert result.classification == "Unclassified"
    assert result.is_unclassified


def test_title_outweighs_transcript():
    # One evergreen phrase in the title (weight 3) beats one trending phrase
    # buried in the transcript (weight 1).
    result = classify("How to bake bread", [], "this is the latest thing")
    assert result.evergreen_score > 50


def test_transcript_alone_still_registers():
    result = classify("Bread", [], "in this tutorial we explain the basics step by step")
    assert result.evergreen_score > 50
    assert not result.is_unclassified


def test_mixed_signals_land_in_the_middle():
    result = classify("How to use the 2026 update", [], None)
    assert 25 <= result.evergreen_score <= 75


def test_year_alone_counts_as_trending():
    result = classify("Best laptops 2026", [], None)
    assert "2026" in result.trending_hits
    assert result.evergreen_score < 50


def test_hits_are_deduplicated_and_lowercased():
    result = classify("How To and how to again", [], "HOW TO once more")
    assert result.evergreen_hits == ["how to"]
