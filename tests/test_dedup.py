"""Semantic deduplication of the candidate pool.

build_pool's dict only collapses byte-identical phrases. The same keyword
really arrives twice by inflection ("certificate"/"certificates"), by word
order, and by connecting words ("student visa for germany"), and each copy
then consumes a slot in a 500-character tag budget.
"""

from autocomplete import Suggestion
from candidates import (
    LANE_COMPETITOR, LANE_DEMAND, LANE_SUPPLY, Candidate, build_pool, deduplicate,
)


def _candidate(phrase, rank=None, hits=0, lanes=()):
    c = Candidate(phrase=phrase, autocomplete_rank=rank, competitor_hits=hits)
    c.lanes = set(lanes)
    return c


# ------------------------------------------------------------ what collapses


def test_inflection_variants_collapse():
    pool = build_pool(["aps certificate germany", "aps certificates germany"], [], [])
    assert len(pool) == 1


def test_word_order_variants_collapse():
    pool = build_pool(["germany student visa", "student visa germany"], [], [])
    assert len(pool) == 1


def test_connecting_words_do_not_make_a_new_keyword():
    pool = build_pool(["student visa for germany", "germany student visa"], [], [])
    assert len(pool) == 1


# --------------------------------------------------------- what must NOT merge


def test_genuinely_different_phrases_stay_separate():
    pool = build_pool(
        ["germany student visa", "germany work visa", "canada student visa"], [], []
    )
    assert len(pool) == 3


def test_a_repeated_word_is_not_the_same_as_one_mention():
    """Signature is a sorted tuple, not a set, so multiplicity survives."""
    kept = deduplicate([_candidate("visa visa germany"), _candidate("visa germany")])
    assert len(kept) == 2


def test_phrases_with_no_comparable_content_are_left_alone():
    """All-stopword phrases have an empty signature; they must not all
    collapse into a single bucket with each other."""
    kept = deduplicate([_candidate("how to the"), _candidate("what is it")])
    assert len(kept) == 2


# -------------------------------------------------------------- evidence merge


def test_competitor_hits_are_summed_across_variants():
    """The signal this protects: two competitors using "germany student visa"
    and one using "student visa germany" is three competitors on one concept.
    Left unmerged they read as 2 and 1, and the 1 is discarded as noise by
    keyword_rank.COMPETITOR_CONSENSUS_MIN."""
    pool = build_pool(
        [], [],
        ["germany student visa", "germany student visa", "student visa germany"],
    )
    assert len(pool) == 1
    assert pool[0].competitor_hits == 3


def test_best_autocomplete_rank_wins():
    kept = deduplicate([
        _candidate("germany student visa", rank=7),
        _candidate("student visa germany", rank=2),
    ])
    assert len(kept) == 1
    assert kept[0].autocomplete_rank == 2


def test_lanes_are_unioned():
    pool = build_pool(
        supply_phrases=["germany student visa"],
        suggestions=[Suggestion("student visa germany", 3, "seed")],
        competitor_phrases=["visa germany student", "visa germany student"],
    )
    assert len(pool) == 1
    assert pool[0].lanes == {LANE_SUPPLY, LANE_DEMAND, LANE_COMPETITOR}


def test_a_variant_never_loses_its_evidence_by_being_absorbed():
    kept = deduplicate([
        _candidate("germany student visa", hits=2, lanes=[LANE_COMPETITOR]),
        _candidate("student visa germany", rank=1, hits=1, lanes=[LANE_DEMAND]),
    ])
    assert kept[0].competitor_hits == 3
    assert kept[0].autocomplete_rank == 1
    assert kept[0].lanes == {LANE_COMPETITOR, LANE_DEMAND}


# ------------------------------------------------------- which spelling wins


def test_the_searched_phrasing_is_the_one_kept():
    """Surface form should be how people actually type it, so a phrase Google
    returned as a suggestion beats one assembled from a transcript."""
    pool = build_pool(
        supply_phrases=["germany student visa requirements list"],
        suggestions=[Suggestion("student visa requirements germany list", 2, "seed")],
        competitor_phrases=[],
    )
    assert pool[0].phrase == "student visa requirements germany list"


def test_better_ranked_suggestion_wins_the_spelling():
    kept = deduplicate([
        _candidate("germany student visa", rank=8),
        _candidate("student visa germany", rank=1),
    ])
    assert kept[0].phrase == "student visa germany"


def test_dedup_is_deterministic_regardless_of_input_order():
    """keyword_rank has a determinism test; this must not become a source of
    run-to-run drift feeding into it."""
    a, b = _candidate("germany student visa"), _candidate("student visa germany")
    forward = deduplicate([a, b])[0].phrase
    backward = deduplicate([
        _candidate("student visa germany"), _candidate("germany student visa")
    ])[0].phrase
    assert forward == backward
