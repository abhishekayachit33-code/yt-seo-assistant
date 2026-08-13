from dataclasses import dataclass

from candidates import LANE_COMPETITOR, LANE_DEMAND, LANE_SUPPLY, Candidate
from keyword_rank import (
    AUTOCOMPLETE_RANK_FLOOR, COMPETITOR_CONSENSUS_MIN, LONGTAIL_MIN_WORDS,
    RELEVANCE_FLOOR, W_COVERAGE_PLANNING_NO_SCRIPT, _split_opening,
    assess_confidence, autocomplete_strength, build_strategy, competitor_strength,
    content_coverage, content_gaps, format_keyword_evidence, head_term_phrases,
    merge_into_tags, rank_keywords, specificity,
)


@dataclass
class FakeSegment:
    text: str
    start: float


def _candidate(phrase, rank=None, hits=0, relevance=0.5, lanes=None):
    return Candidate(
        phrase=phrase, lanes=lanes or set(),
        autocomplete_rank=rank, competitor_hits=hits, relevance=relevance,
    )


# ------------------------------------------------------------- normalization


def test_every_feature_stays_within_zero_and_one():
    # Normalization is what makes the weights interpretable and stops a
    # length-biased feature quietly dominating the score.
    for phrase in ["a", "aps certificate germany requirements for indian students", "tips"]:
        assert 0.0 <= specificity(phrase) <= 1.0
    for rank in [None, 0, 5, 50]:
        assert 0.0 <= autocomplete_strength(rank) <= 1.0
    for hits in [0, 1, 5, 100]:
        assert 0.0 <= competitor_strength(hits) <= 1.0
    assert 0.0 <= content_coverage("x y", "x", "y", None, "x y " * 500) <= 1.0


# ---------------------------------------------------------------- specificity


def test_longer_phrases_are_more_specific():
    assert specificity("aps certificate germany") > specificity("germany")


def test_generic_words_reduce_specificity():
    assert specificity("aps certificate germany") > specificity("best tips guide")


def test_specificity_of_empty_phrase_is_zero():
    assert specificity("") == 0.0


# ------------------------------------------------------- autocomplete strength


def test_better_autocomplete_position_scores_higher():
    assert autocomplete_strength(0) > autocomplete_strength(5)


def test_missing_autocomplete_rank_scores_zero():
    assert autocomplete_strength(None) == 0.0


def test_ranks_past_the_floor_score_zero():
    assert autocomplete_strength(AUTOCOMPLETE_RANK_FLOOR) == 0.0
    assert autocomplete_strength(AUTOCOMPLETE_RANK_FLOOR + 50) == 0.0


# ------------------------------------------------------------------- coverage


def test_coverage_matches_on_words_not_exact_phrase():
    # "the APS certificate ... going to Germany" genuinely covers this keyword,
    # even though the exact contiguous string never appears.
    score = content_coverage(
        "aps certificate germany",
        title="",
        description="Everything about the APS certificate for students going to Germany",
    )
    assert score > 0


def test_title_placement_beats_description_placement():
    in_title = content_coverage("aps certificate", title="APS Certificate Guide", description="")
    in_description = content_coverage("aps certificate", title="", description="APS Certificate Guide")
    assert in_title > in_description


def test_description_opening_beats_a_passing_mention_later_on():
    # The real bug, reproduced verbatim from the LetzStudy "France" video: a
    # word that appears once in a throwaway list near the end of the
    # description ("scholarships") must not outscore a phrase describing the
    # video's actual stated subject, sitting in the opening sentence.
    description = (
        "Top Public Universities in France for Global Students are becoming the top "
        "choice for international learners looking for affordable, high-quality "
        "education. In this video, we reveal the best universities in France for "
        "global students planning to study abroad. Whether you want world-class "
        "research, scholarships, or multicultural campus life, France offers it all."
    )
    subject = content_coverage("top universities in france", title="", description=description)
    passing_mention = content_coverage("scholarships in france", title="", description=description)
    assert subject > passing_mention


def test_split_opening_cuts_at_first_sentence():
    opening, rest = _split_opening("First sentence. Second sentence.")
    assert opening == "First sentence. "
    assert rest == "Second sentence."


def test_split_opening_falls_back_to_max_chars_without_punctuation():
    text = "a" * 300  # no sentence-ending punctuation anywhere
    opening, rest = _split_opening(text, max_chars=160)
    assert len(opening) == 160
    assert len(rest) == 140


def test_split_opening_caps_a_long_first_sentence():
    text = ("word " * 100) + "."  # one very long sentence before the period
    opening, rest = _split_opening(text, max_chars=160)
    assert len(opening) == 160


def test_split_opening_empty_text():
    assert _split_opening("") == ("", "")


def test_early_transcript_mention_beats_late_one():
    segments_early = [FakeSegment("aps certificate explained", 0.0), FakeSegment("unrelated", 100.0)]
    segments_late = [FakeSegment("unrelated", 0.0), FakeSegment("aps certificate explained", 100.0)]
    early = content_coverage("aps certificate", "", "", segments_early)
    late = content_coverage("aps certificate", "", "", segments_late)
    assert early > late


def test_uncovered_keyword_scores_zero():
    assert content_coverage("quantum physics", "APS certificate guide", "germany visa") == 0.0


def test_coverage_is_not_inflated_by_a_longer_transcript():
    # The same keyword, same relative prominence, in a short vs long video --
    # a raw hit count would score the long one higher for being long.
    short = content_coverage("aps certificate", "", "", None, "aps certificate " * 5)
    long = content_coverage("aps certificate", "", "", None, "aps certificate " * 500)
    assert short == long


# ---------------------------------------------------------------- competitors


def test_single_competitor_is_discarded_not_down_weighted():
    # One competitor's tag is one person's guess, not evidence.
    assert competitor_strength(1) == 0.0


def test_consensus_across_competitors_counts():
    assert competitor_strength(COMPETITOR_CONSENSUS_MIN) > 0.0
    assert competitor_strength(5) > competitor_strength(COMPETITOR_CONSENSUS_MIN)


# -------------------------------------------------------------------- ranking


def test_ranking_is_deterministic():
    # The whole reason ranking lives in Python and not in the model.
    pool = [_candidate("aps certificate germany", rank=0), _candidate("germany", rank=5)]
    first = [k.phrase for k in rank_keywords(pool, "t", "d")]
    second = [k.phrase for k in rank_keywords(pool, "t", "d")]
    assert first == second


def test_ranking_works_without_llm_intents():
    # Judge failure must not stop a ranking being produced.
    pool = [_candidate("aps certificate")]
    ranked = rank_keywords(pool, "t", "d", intents=None)
    assert ranked[0].intent == "unknown"


def test_informational_intent_outranks_transactional_all_else_equal():
    pool = [_candidate("alpha beta gamma"), _candidate("alpha beta delta")]
    ranked = rank_keywords(pool, "", "", intents={
        "alpha beta gamma": "informational",
        "alpha beta delta": "transactional",
    })
    assert ranked[0].phrase == "alpha beta gamma"


def test_off_topic_keyword_cannot_win_on_other_features_alone():
    # Real bug, reproduced: "jinnah international airport" scored a well-
    # suggested rank 0 (max autocomplete strength) and, being three specific
    # words, a high specificity score -- enough combined to outrank a
    # genuinely relevant keyword despite being almost entirely off-topic
    # (relevance 0.15). Relevance must gate, not just contribute to the sum.
    off_topic = _candidate("jinnah international airport", rank=0, relevance=0.15)
    on_topic = _candidate("aps certificate germany", rank=5, relevance=0.5)
    ranked = rank_keywords([off_topic, on_topic], "t", "d")
    phrases = [k.phrase for k in ranked]
    assert "jinnah international airport" not in phrases
    assert phrases == ["aps certificate germany"]


def test_relevance_floor_drops_candidates_below_it_entirely():
    below = _candidate("below floor", relevance=RELEVANCE_FLOOR - 0.01)
    above = _candidate("above floor", relevance=RELEVANCE_FLOOR + 0.01)
    ranked = rank_keywords([below, above], "t", "d")
    assert [k.phrase for k in ranked] == ["above floor"]


def test_all_candidates_below_the_floor_yields_an_empty_ranking():
    pool = [_candidate("junk one", relevance=0.0), _candidate("junk two", relevance=0.05)]
    assert rank_keywords(pool, "t", "d") == []


def test_every_ranked_keyword_carries_evidence():
    pool = [_candidate("aps certificate germany", rank=1, hits=3)]
    ranked = rank_keywords(pool, "APS certificate", "germany guide")
    assert ranked[0].evidence
    assert any("position 2" in e for e in ranked[0].evidence)


# ------------------------------------------------------------------- strategy


def test_primary_is_a_head_term_not_a_long_question():
    pool = [
        _candidate("is aps certificate required for indian students", rank=0, relevance=0.9),
        _candidate("aps certificate germany", rank=1, relevance=0.8),
    ]
    strategy = build_strategy(rank_keywords(pool, "", ""), [LANE_DEMAND])
    assert strategy.primary.candidate.word_count < LONGTAIL_MIN_WORDS


def test_long_tail_holds_the_longer_phrases():
    pool = [
        _candidate("aps certificate", rank=0),
        _candidate("how to get aps certificate in germany", rank=1),
    ]
    strategy = build_strategy(rank_keywords(pool, "", ""), [LANE_DEMAND])
    assert all(k.candidate.word_count >= LONGTAIL_MIN_WORDS for k in strategy.long_tail)


def test_primary_never_repeats_in_secondary_or_long_tail():
    pool = [_candidate(f"phrase {i} here", rank=i) for i in range(12)]
    strategy = build_strategy(rank_keywords(pool, "", ""), [LANE_DEMAND])
    others = {k.phrase for k in strategy.secondary + strategy.long_tail}
    assert strategy.primary.phrase not in others


def test_empty_ranking_produces_an_empty_strategy():
    strategy = build_strategy([], [])
    assert strategy.primary is None
    assert strategy.secondary == []


# ----------------------------------------------------------------- confidence


def test_all_lanes_present_gives_high_confidence():
    level, _ = assess_confidence([LANE_DEMAND, LANE_SUPPLY, LANE_COMPETITOR], 30)
    assert level == "high"


def test_missing_lanes_lower_the_confidence():
    level, reason = assess_confidence([LANE_SUPPLY], 30)
    assert level == "low"
    assert "suggestions" in reason


def test_confidence_reason_names_what_was_missing():
    _, reason = assess_confidence([LANE_DEMAND, LANE_SUPPLY], 30)
    assert "competitor" in reason.lower()


# ---------------------------------------------------------- tags/keywords merge


def test_head_term_phrases_includes_primary_and_secondary():
    pool = [_candidate("aps certificate germany", rank=0), _candidate("aps certificate fees", rank=1)]
    strategy = build_strategy(rank_keywords(pool, "", ""), [LANE_DEMAND])
    phrases = head_term_phrases(strategy)
    assert strategy.primary.phrase in phrases
    for k in strategy.secondary:
        assert k.phrase in phrases


def test_head_term_phrases_excludes_long_tail():
    pool = [
        _candidate("aps certificate germany", rank=0),
        _candidate("how to get aps certificate in germany fast", rank=1),
    ]
    strategy = build_strategy(rank_keywords(pool, "", ""), [LANE_DEMAND])
    phrases = head_term_phrases(strategy)
    assert not any(k.candidate.word_count >= LONGTAIL_MIN_WORDS for k in strategy.long_tail if k.phrase in phrases)


def test_head_term_phrases_empty_when_no_primary():
    empty_strategy = build_strategy([], [])
    assert head_term_phrases(empty_strategy) == []


def test_merge_into_tags_adds_new_head_terms():
    pool = [_candidate("aps certificate germany", rank=0)]
    strategy = build_strategy(rank_keywords(pool, "", ""), [LANE_DEMAND])
    merged = merge_into_tags(["existing tag"], strategy)
    assert "existing tag" in merged
    assert "aps certificate germany" in merged


def test_merge_into_tags_is_case_insensitive_deduplication():
    pool = [_candidate("aps certificate germany", rank=0)]
    strategy = build_strategy(rank_keywords(pool, "", ""), [LANE_DEMAND])
    merged = merge_into_tags(["APS Certificate Germany"], strategy)
    assert merged.count("APS Certificate Germany") == 1
    assert "aps certificate germany" not in merged  # not added again in a different case


def test_merge_into_tags_preserves_existing_tag_order_first():
    pool = [_candidate("aps certificate germany", rank=0)]
    strategy = build_strategy(rank_keywords(pool, "", ""), [LANE_DEMAND])
    merged = merge_into_tags(["a", "b", "c"], strategy)
    assert merged[:3] == ["a", "b", "c"]


def test_merge_into_tags_is_a_noop_with_no_strategy_primary():
    empty_strategy = build_strategy([], [])
    assert merge_into_tags(["a", "b"], empty_strategy) == ["a", "b"]


# --------------------------------------------------------------- prompt evidence


def test_format_keyword_evidence_includes_primary_and_its_evidence():
    pool = [_candidate("aps certificate germany", rank=0)]
    strategy = build_strategy(rank_keywords(pool, "APS certificate", "germany"), [LANE_DEMAND])
    text = format_keyword_evidence(strategy)
    assert "aps certificate germany" in text
    assert "position 1" in text  # evidence string, not just the bare phrase


def test_format_keyword_evidence_includes_secondary_terms():
    pool = [_candidate("aps certificate germany", rank=0), _candidate("aps certificate fees", rank=1)]
    strategy = build_strategy(rank_keywords(pool, "", ""), [LANE_DEMAND])
    text = format_keyword_evidence(strategy)
    for keyword in strategy.secondary:
        assert keyword.phrase in text


def test_format_keyword_evidence_excludes_long_tail():
    pool = [
        _candidate("aps certificate germany", rank=0),
        _candidate("how to get aps certificate in germany fast", rank=1),
    ]
    strategy = build_strategy(rank_keywords(pool, "", ""), [LANE_DEMAND])
    text = format_keyword_evidence(strategy)
    for keyword in strategy.long_tail:
        assert keyword.phrase not in text


def test_format_keyword_evidence_is_empty_string_with_no_primary():
    empty_strategy = build_strategy([], [])
    assert format_keyword_evidence(empty_strategy) == ""


# ------------------------------------------------------------- planning mode


def test_planning_without_a_script_zeroes_the_coverage_weight():
    # Coverage of a video that does not exist is unmeasurable. Leaving its
    # weight in place would compress every score toward the same value
    # rather than being neutral.
    assert W_COVERAGE_PLANNING_NO_SCRIPT == 0.0


def test_planning_no_script_ignores_coverage_in_the_ordering():
    # Two candidates identical except that one appears in the draft title.
    # In analyze mode that decides the order; in planning-without-script it
    # must not, because there is no video to have covered anything.
    in_title = _candidate("aps certificate germany", rank=3)
    not_in_title = _candidate("germany student visa", rank=0)

    live = rank_keywords([in_title, not_in_title], "APS Certificate Germany", "")
    planned = rank_keywords(
        [in_title, not_in_title], "APS Certificate Germany", "", planning=True
    )
    # Live: coverage pulls the title-matching phrase up. Planning: it can't,
    # so the stronger autocomplete position wins instead.
    assert live[0].phrase == "aps certificate germany"
    assert planned[0].phrase == "germany student visa"


def test_planning_evidence_reads_as_opportunity_not_warning():
    pool = [_candidate("aps certificate germany", rank=0)]
    ranked = rank_keywords(pool, "Unrelated title", "unrelated description",
                           transcript_text="a draft script about something else",
                           planning=True)
    joined = " ".join(ranked[0].evidence)
    assert "draft doesn't mention this yet" in joined
    assert "does not currently cover" not in joined


def test_analyze_evidence_still_reads_as_a_warning():
    pool = [_candidate("aps certificate germany", rank=0)]
    ranked = rank_keywords(pool, "Unrelated title", "unrelated description")
    joined = " ".join(ranked[0].evidence)
    assert "your video does not currently cover this" in joined


def test_planning_without_a_script_makes_no_coverage_claim_at_all():
    # With nothing to measure against, asserting either "covers this" or
    # "doesn't cover this" would be inventing a verdict.
    pool = [_candidate("aps certificate germany", rank=0)]
    ranked = rank_keywords(pool, "Some title", "", planning=True)
    joined = " ".join(ranked[0].evidence)
    assert "cover" not in joined
    assert "mention" not in joined


# ----------------------------------------------------------------- content gaps


def test_content_gaps_surface_in_demand_phrases_the_draft_misses():
    covered = _candidate("aps certificate germany", rank=0)
    missing = _candidate("germany blocked account", rank=0)
    ranked = rank_keywords(
        [covered, missing],
        title="APS Certificate Germany",
        description="all about the aps certificate germany process",
        planning=True,
    )
    strategy = build_strategy(ranked, [LANE_DEMAND])
    gap_phrases = [k.phrase for k in content_gaps(strategy)]
    assert "germany blocked account" in gap_phrases
    assert "aps certificate germany" not in gap_phrases


def test_content_gaps_require_real_demand_not_just_absence():
    # A phrase with no autocomplete position is not "demand the draft
    # misses", it is just an unrelated phrase the draft happens not to
    # mention -- which is true of almost everything.
    no_demand = _candidate("some unrelated phrase", rank=None)
    ranked = rank_keywords([no_demand], "Title", "description", planning=True)
    strategy = build_strategy(ranked, [LANE_DEMAND])
    assert content_gaps(strategy) == []


def test_content_gaps_empty_for_an_empty_strategy():
    assert content_gaps(build_strategy([], [])) == []
