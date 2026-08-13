from autocomplete import Suggestion
from candidates import (
    LANE_COMPETITOR, LANE_DEMAND, LANE_SUPPLY,
    build_pool, score_relevance, shortlist,
)


def _suggestion(phrase, rank=0):
    return Suggestion(phrase=phrase, rank=rank, seed="seed")


def test_pool_merges_lanes_onto_one_candidate():
    pool = build_pool(
        supply_phrases=["aps certificate"],
        suggestions=[_suggestion("aps certificate", rank=2)],
        competitor_phrases=["aps certificate"],
    )
    assert len(pool) == 1
    candidate = pool[0]
    assert candidate.lanes == {LANE_SUPPLY, LANE_DEMAND, LANE_COMPETITOR}
    assert candidate.autocomplete_rank == 2
    assert candidate.competitor_hits == 1


def test_pool_counts_competitor_repeats_rather_than_collapsing_them():
    # The repeat count IS the consensus signal -- a set() here would destroy it.
    pool = build_pool(competitor_phrases=["visa process"] * 4)
    assert pool[0].competitor_hits == 4


def test_pool_keeps_the_best_autocomplete_rank():
    pool = build_pool(suggestions=[
        _suggestion("germany visa", rank=7),
        _suggestion("germany visa", rank=1),
    ])
    assert pool[0].autocomplete_rank == 1


def test_pool_normalizes_case_and_whitespace():
    pool = build_pool(supply_phrases=["  APS   Certificate  ", "aps certificate"])
    assert len(pool) == 1
    assert pool[0].phrase == "aps certificate"


def test_junk_phrases_are_filtered():
    pool = build_pool(supply_phrases=[
        "how to",              # junk standalone
        "best",                # junk standalone
        "https://spam.com",    # url
        "12345",               # non-text
        "a",                   # too short
        "the and of",          # all stopwords
        "aps certificate",     # keeper
    ])
    assert [c.phrase for c in pool] == ["aps certificate"]


def test_overlong_phrases_are_filtered():
    pool = build_pool(supply_phrases=["word " * 12])
    assert pool == []


def test_relevance_scores_on_topic_above_off_topic():
    pool = build_pool(supply_phrases=[
        "aps certificate germany",
        "chocolate cake recipe",
    ])
    score_relevance(pool, "A guide to the APS certificate for students going to Germany")
    by_phrase = {c.phrase: c.relevance for c in pool}
    assert by_phrase["aps certificate germany"] > by_phrase["chocolate cake recipe"]


def test_relevance_is_a_noop_with_empty_reference():
    pool = build_pool(supply_phrases=["aps certificate"])
    score_relevance(pool, "   ")
    assert pool[0].relevance == 0.0


def test_shortlist_caps_and_orders_by_relevance():
    pool = build_pool(supply_phrases=[f"phrase number {i}" for i in range(60)])
    for i, candidate in enumerate(pool):
        candidate.relevance = i / 100
    top = shortlist(pool, limit=10)
    assert len(top) == 10
    assert top[0].relevance >= top[-1].relevance


def test_empty_inputs_produce_an_empty_pool():
    assert build_pool() == []
