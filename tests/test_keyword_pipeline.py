from unittest.mock import patch

from autocomplete import Suggestion
from candidates import LANE_COMPETITOR, LANE_DEMAND, LANE_SUPPLY
from keyword_pipeline import _competitor_phrases, build_seeds, run

SUMMARY = (
    "This video explains the APS Certificate process for Indian Students "
    "applying to German Universities, including documents and fees."
)
TITLE = "Study in Germany: APS Certificate Full Process for Indian Students"


class FakeCompetitor:
    def __init__(self, title, tags=None):
        self.title = title
        self.tags = tags or []


# ----------------------------------------------------------------- seeds


def test_seeds_prefer_named_entities():
    seeds = build_seeds(SUMMARY, TITLE)
    assert "aps certificate" in seeds


def test_seeds_reject_narration_filler():
    # "video explains" / "process required" are the exact junk bigrams a
    # naive frequency extractor produces on a short summary.
    seeds = build_seeds(SUMMARY, TITLE)
    assert not any("explains" in s or "required" in s for s in seeds)


def test_seeds_include_existing_tags():
    seeds = build_seeds(SUMMARY, TITLE, existing_tags=["study abroad"])
    assert "study abroad" in seeds


def test_seeds_are_capped():
    seeds = build_seeds(SUMMARY, TITLE, existing_tags=[f"tag {i}" for i in range(20)])
    assert len(seeds) <= 6


def test_seeds_are_deduplicated():
    seeds = build_seeds(SUMMARY, TITLE, existing_tags=["aps certificate", "APS Certificate"])
    assert len(seeds) == len(set(seeds))


def test_short_transcripts_do_not_contribute_seeds():
    # Frequency is meaningless over a few sentences -- every bigram appears
    # once, so the "top" ones would be arbitrary.
    with_short = build_seeds("", "", transcript="a short transcript about things")
    assert with_short == []


# ---------------------------------------------------------- competitor lane


def test_competitor_titles_are_decomposed_into_phrases():
    phrases = _competitor_phrases([FakeCompetitor("APS Certificate Germany Guide")])
    assert any("aps certificate" in p for p in phrases)


def test_competitor_duplicates_are_preserved_for_consensus():
    competitors = [FakeCompetitor("", ["visa process"]) for _ in range(3)]
    phrases = _competitor_phrases(competitors)
    assert phrases.count("visa process") == 3


def test_no_competitors_yields_no_phrases():
    assert _competitor_phrases([]) == []
    assert _competitor_phrases(None) == []


# -------------------------------------------------------------- full run


@patch("keyword_pipeline.autocomplete.collect")
def test_run_produces_a_strategy_from_demand_alone(mock_collect):
    mock_collect.return_value = [
        Suggestion("aps certificate germany", 0, "aps certificate"),
        Suggestion("how to get aps certificate in germany", 1, "aps certificate"),
    ]
    result = run([], SUMMARY, TITLE, "desc", use_llm_judge=False)
    assert result.strategy.primary is not None
    assert LANE_DEMAND in result.lanes_used


@patch("keyword_pipeline.autocomplete.collect")
def test_run_degrades_when_autocomplete_is_blocked(mock_collect):
    mock_collect.return_value = []
    result = run(
        [], SUMMARY, TITLE, "desc",
        transcript="aps certificate germany. aps certificate germany again. " * 20,
        use_llm_judge=False,
    )
    assert LANE_DEMAND not in result.lanes_used
    assert LANE_SUPPLY in result.lanes_used
    assert result.strategy.confidence in ("low", "medium")


@patch("keyword_pipeline.autocomplete.collect")
def test_run_with_no_evidence_at_all_returns_empty_not_a_crash(mock_collect):
    mock_collect.return_value = []
    result = run([], "", "", "", use_llm_judge=False)
    assert result.strategy.primary is None
    assert result.candidate_count == 0


@patch("keyword_pipeline.judge_keywords")
@patch("keyword_pipeline.autocomplete.collect")
def test_llm_judge_drops_rejected_candidates(mock_collect, mock_judge):
    mock_collect.return_value = [
        Suggestion(f"aps certificate variant {i}", i, "aps") for i in range(10)
    ] + [Suggestion("completely unrelated chocolate cake", 0, "aps")]
    mock_judge.return_value = {
        f"aps certificate variant {i}": {"keep": True, "intent": "informational", "topic": "aps"}
        for i in range(10)
    } | {"completely unrelated chocolate cake": {"keep": False, "intent": "unknown", "topic": ""}}

    result = run(["key"], SUMMARY, TITLE, "desc", use_llm_judge=True)
    phrases = {k.phrase for k in result.strategy.all_keywords}
    assert "completely unrelated chocolate cake" not in phrases


@patch("keyword_pipeline.judge_keywords")
@patch("keyword_pipeline.autocomplete.collect")
def test_pipeline_survives_the_judge_failing(mock_collect, mock_judge):
    mock_collect.return_value = [Suggestion("aps certificate germany", 0, "aps")]
    mock_judge.return_value = {}  # judge_keywords swallows its own errors
    result = run(["key"], SUMMARY, TITLE, "desc", use_llm_judge=True)
    assert result.strategy.primary is not None
    assert result.judged_count == 0


@patch("keyword_pipeline.judge_keywords")
@patch("keyword_pipeline.autocomplete.collect")
def test_wholesale_rejection_by_the_judge_is_ignored(mock_collect, mock_judge):
    # A judge that rejects everything is far more likely broken than correct,
    # so the deterministic shortlist wins. Phrases share real vocabulary with
    # SUMMARY/TITLE (not filler like "variant N") so they clear the relevance
    # floor and this test actually exercises the judge-rejection path rather
    # than being cut earlier for being off-topic.
    phrases = [
        "aps certificate germany", "aps certificate fees", "aps certificate documents",
        "aps certificate timeline", "aps certificate indian students",
    ]
    mock_collect.return_value = [Suggestion(p, i, "aps") for i, p in enumerate(phrases)]
    mock_judge.return_value = {p: {"keep": False, "intent": "unknown", "topic": ""} for p in phrases}
    result = run(["key"], SUMMARY, TITLE, "desc", use_llm_judge=True)
    assert result.strategy.primary is not None


@patch("keyword_pipeline.autocomplete.collect")
def test_competitor_lane_registers_when_supplied(mock_collect):
    mock_collect.return_value = []
    result = run(
        [], SUMMARY, TITLE, "desc",
        competitors=[FakeCompetitor("APS Certificate Germany Guide") for _ in range(3)],
        use_llm_judge=False,
    )
    assert LANE_COMPETITOR in result.lanes_used


@patch("keyword_pipeline.autocomplete.collect")
def test_no_gemini_keys_skips_the_judge_entirely(mock_collect):
    mock_collect.return_value = [Suggestion("aps certificate germany", 0, "aps")]
    with patch("keyword_pipeline.judge_keywords") as mock_judge:
        run([], SUMMARY, TITLE, "desc", use_llm_judge=True)
        mock_judge.assert_not_called()


# ------------------------------------------------------ weak-evidence fallback


@patch("keyword_pipeline.autocomplete.collect")
def test_falls_back_to_closest_matches_when_nothing_clears_the_floor(mock_collect):
    # Candidates that exist but share almost no vocabulary with SUMMARY/TITLE
    # -- everything scores below RELEVANCE_FLOOR. Must not come back empty.
    mock_collect.return_value = [
        Suggestion("completely unrelated topic about cooking recipes", 0, "x"),
    ]
    result = run([], SUMMARY, TITLE, "desc", use_llm_judge=False)
    assert result.weak_evidence is True
    assert result.strategy.primary is not None


@patch("keyword_pipeline.autocomplete.collect")
def test_no_fallback_needed_when_real_matches_clear_the_floor(mock_collect):
    mock_collect.return_value = [Suggestion("aps certificate germany", 0, "aps")]
    result = run([], SUMMARY, TITLE, "desc", use_llm_judge=False)
    assert result.weak_evidence is False


@patch("keyword_pipeline.autocomplete.collect")
def test_truly_empty_pool_is_not_reported_as_weak_evidence(mock_collect):
    # No candidates at all is a different failure mode from "candidates
    # existed but were all irrelevant" -- must not be conflated.
    mock_collect.return_value = []
    result = run([], "", "", "", use_llm_judge=False)
    assert result.weak_evidence is False
    assert result.candidate_count == 0
