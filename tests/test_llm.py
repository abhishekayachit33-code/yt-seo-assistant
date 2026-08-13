import json
from unittest.mock import MagicMock, patch

from limits import TAGS_MAX
from llm import (
    MIN_TAGS, SEO_SCHEMA, _candidate_phrases, enforce_tag_char_limit,
    find_output_violations, generate_seo, understand_video,
)


def _data(tags=None, chapters=None):
    return {
        "tags": tags if tags is not None else [f"tag{i}" for i in range(MIN_TAGS)],
        "chapters": chapters if chapters is not None else [],
    }


def test_enough_tags_no_violation():
    data = _data(tags=[f"tag{i}" for i in range(MIN_TAGS)])
    violations = find_output_violations(data, has_transcript=False)
    assert not any(v.field == "tags" for v in violations)


def test_too_few_tags_flagged():
    data = _data(tags=["only", "a", "few"])
    violations = find_output_violations(data, has_transcript=False)
    assert any(v.field == "tags" for v in violations)


def test_chapters_without_transcript_flagged():
    data = _data(chapters=[{"timestamp": "00:00", "title": "Intro"}])
    violations = find_output_violations(data, has_transcript=False)
    assert any(v.field == "chapters" and "no transcript" in v.reason for v in violations)


def test_valid_chapters_with_transcript_no_violation():
    data = _data(chapters=[
        {"timestamp": "00:00", "title": "Intro"},
        {"timestamp": "00:20", "title": "Main"},
        {"timestamp": "00:45", "title": "Outro"},
    ])
    violations = find_output_violations(data, has_transcript=True)
    assert not any(v.field == "chapters" for v in violations)


def test_first_chapter_not_zero_flagged():
    data = _data(chapters=[{"timestamp": "00:15", "title": "Intro"}])
    violations = find_output_violations(data, has_transcript=True)
    assert any("00:00" in v.reason for v in violations)


def test_chapters_too_close_together_flagged():
    data = _data(chapters=[
        {"timestamp": "00:00", "title": "Intro"},
        {"timestamp": "00:05", "title": "Too soon"},
    ])
    violations = find_output_violations(data, has_transcript=True)
    assert any("close together" in v.reason for v in violations)


def test_no_chapters_with_transcript_is_not_a_violation():
    data = _data(chapters=[])
    violations = find_output_violations(data, has_transcript=True)
    assert not any(v.field == "chapters" for v in violations)


def test_oversized_combined_tags_flagged():
    # Reproduces a real production case: 35+ tags satisfying the count
    # minimum but totalling 991 combined characters against a 500 limit.
    long_tags = [f"a fairly long and specific seo keyword phrase number {i}" for i in range(35)]
    assert len(", ".join(long_tags)) > TAGS_MAX
    data = _data(tags=long_tags)
    violations = find_output_violations(data, has_transcript=False)
    assert any(v.field == "tags" and "500" in v.reason for v in violations)


def test_tags_under_char_limit_not_flagged():
    data = _data(tags=[f"tag{i}" for i in range(MIN_TAGS)])
    violations = find_output_violations(data, has_transcript=False)
    assert not any("characters" in v.reason for v in violations if v.field == "tags")


def test_enforce_tag_char_limit_trims_to_fit():
    long_tags = [f"a fairly long and specific seo keyword phrase number {i}" for i in range(35)]
    trimmed = enforce_tag_char_limit(long_tags)
    assert len(", ".join(trimmed)) <= TAGS_MAX
    assert trimmed == long_tags[: len(trimmed)]  # order preserved, no gaps


def test_enforce_tag_char_limit_is_a_noop_when_already_compliant():
    tags = [f"tag{i}" for i in range(MIN_TAGS)]
    assert enforce_tag_char_limit(tags) == tags


def test_enforce_tag_char_limit_handles_empty_list():
    assert enforce_tag_char_limit([]) == []


def test_enforce_tag_char_limit_accounts_for_separators():
    # Ten 49-char tags = 490 chars of tag text + 9 * ", " (18) = 508 > 500,
    # so the boundary case must actually drop the tag that overflows the
    # separator, not just the tag's own length.
    tags = ["x" * 49] * 10
    trimmed = enforce_tag_char_limit(tags, max_chars=500)
    assert len(", ".join(trimmed)) <= 500
    assert len(trimmed) == 9


def _full_response(chapters=None):
    payload = {
        "tags": [f"tag{i}" for i in range(MIN_TAGS)],
        "chapters": chapters if chapters is not None else [],
        "suggestions": ["do a thing"],
        "titles": ["A title"],
        "description": "A description",
        "hashtags": ["#a", "#b"],
        "hook_analysis": {"verdict": "strong", "reasoning": "r", "rewrite": ""},
        "comment_sentiment": {"positive_themes": [], "negative_themes": [], "summary": ""},
        "shorts_scripts": [],
        "social_posts": {"twitter_thread": "", "linkedin_post": "", "community_post": ""},
    }
    response = MagicMock()
    response.text = json.dumps(payload)
    return response


@patch("llm.generate_content_with_fallback")
def test_suppress_chapters_forces_empty_list_even_if_model_returns_some(mock_generate):
    # The model "misbehaving" and returning chapters anyway is exactly the
    # scenario the deterministic backstop exists for -- repair_output() runs
    # against the base SYSTEM_PROMPT and could reintroduce them.
    mock_generate.return_value = _full_response(
        chapters=[{"timestamp": "00:00", "title": "Fabricated"}]
    )
    data = generate_seo(
        api_keys=["k"], title="t", description="d", existing_tags=[],
        transcript="a pasted script", suppress_chapters=True,
    )
    assert data["chapters"] == []


@patch("llm.generate_content_with_fallback")
def test_chapters_kept_when_not_suppressed(mock_generate):
    mock_generate.return_value = _full_response(
        chapters=[{"timestamp": "00:00", "title": "Intro"}, {"timestamp": "00:20", "title": "Main"}]
    )
    data = generate_seo(
        api_keys=["k"], title="t", description="d", existing_tags=[],
        transcript="a real transcript", suppress_chapters=False,
    )
    assert len(data["chapters"]) == 2


@patch("llm.generate_content_with_fallback")
def test_suppress_chapters_adds_override_to_system_prompt(mock_generate):
    mock_generate.return_value = _full_response()
    generate_seo(
        api_keys=["k"], title="t", description="d", existing_tags=[],
        transcript=None, suppress_chapters=True,
    )
    system_instruction = mock_generate.call_args.kwargs["config"].system_instruction
    assert "has not been recorded or uploaded yet" in system_instruction


@patch("llm.generate_content_with_fallback")
def test_no_suppress_chapters_leaves_system_prompt_unchanged(mock_generate):
    mock_generate.return_value = _full_response()
    generate_seo(
        api_keys=["k"], title="t", description="d", existing_tags=[],
        transcript=None, suppress_chapters=False,
    )
    system_instruction = mock_generate.call_args.kwargs["config"].system_instruction
    assert "has not been recorded or uploaded yet" not in system_instruction


@patch("llm.generate_content_with_fallback")
def test_missing_rationale_fields_default_to_empty_string(mock_generate):
    # _full_response() omits titles_rationale/tags_rationale entirely -- older
    # cached results and any model response that skips them must not crash.
    mock_generate.return_value = _full_response()
    data = generate_seo(
        api_keys=["k"], title="t", description="d", existing_tags=[], transcript=None,
    )
    assert data["titles_rationale"] == ""
    assert data["tags_rationale"] == ""


@patch("llm.generate_content_with_fallback")
def test_rationale_fields_pass_through_when_provided(mock_generate):
    response = _full_response()
    payload = json.loads(response.text)
    payload["titles_rationale"] = "Leads with a number for curiosity."
    payload["tags_rationale"] = "Prioritizes long-tail phrases from the transcript."
    response.text = json.dumps(payload)
    mock_generate.return_value = response

    data = generate_seo(
        api_keys=["k"], title="t", description="d", existing_tags=[], transcript=None,
    )
    assert data["titles_rationale"] == "Leads with a number for curiosity."
    assert data["tags_rationale"] == "Prioritizes long-tail phrases from the transcript."


def test_schema_generates_analysis_fields_before_tags():
    # Property order is generation order -- content_summary and hook_analysis
    # must stay ahead of tags so tags are conditioned on that analysis.
    keys = list(SEO_SCHEMA["properties"])
    assert keys.index("content_summary") < keys.index("tags")
    assert keys.index("hook_analysis") < keys.index("tags")


def test_candidate_phrases_are_empty_without_a_transcript():
    assert _candidate_phrases(None) == []
    assert _candidate_phrases("") == []


def test_candidate_phrases_skips_phrases_said_only_once():
    # "machine learning" appears twice, "unique phrase here" only once.
    transcript = "machine learning is great. machine learning wins. unique phrase here."
    phrases = _candidate_phrases(transcript)
    assert any("machine learning" in p for p in phrases)
    assert not any("unique phrase here" == p for p in phrases)


@patch("llm.generate_content_with_fallback")
def test_candidate_phrases_are_sent_in_the_prompt(mock_generate):
    mock_generate.return_value = _full_response()
    transcript = "aps certificate germany matters. aps certificate germany is required."
    generate_seo(
        api_keys=["k"], title="t", description="d", existing_tags=[], transcript=transcript,
    )
    sent = mock_generate.call_args.kwargs["contents"]
    assert "Candidate phrases" in sent
    assert "aps certificate germany" in sent


@patch("llm.generate_content_with_fallback")
def test_constraints_are_restated_at_the_end_of_the_prompt(mock_generate):
    mock_generate.return_value = _full_response()
    generate_seo(
        api_keys=["k"], title="t", description="d", existing_tags=[],
        transcript="some transcript text here",
    )
    sent = mock_generate.call_args.kwargs["contents"]
    # Must be last: that recency is the entire point of restating them.
    assert sent.rstrip().endswith("YouTube advice.")
    assert sent.index("Reminder of the hard requirements") > sent.index("Transcript:")


@patch("llm.generate_content_with_fallback")
def test_violations_are_logged_even_when_repair_succeeds(mock_generate, caplog):
    too_few_tags = _full_response(chapters=None)
    payload = json.loads(too_few_tags.text)
    payload["tags"] = ["only", "a", "few"]
    too_few_tags.text = json.dumps(payload)

    mock_generate.side_effect = [too_few_tags, _full_response()]

    with caplog.at_level("WARNING", logger="llm"):
        generate_seo(api_keys=["k"], title="t", description="d", existing_tags=[], transcript=None)

    assert any("violated constraints" in r.message for r in caplog.records)


@patch("llm.generate_content_with_fallback")
def test_repair_failure_is_logged_not_swallowed_silently(mock_generate, caplog):
    too_few_tags = _full_response(chapters=None)
    payload = json.loads(too_few_tags.text)
    payload["tags"] = ["only", "a", "few"]
    too_few_tags.text = json.dumps(payload)

    mock_generate.side_effect = [too_few_tags, Exception("repair call failed")]

    with caplog.at_level("WARNING", logger="llm"):
        data = generate_seo(api_keys=["k"], title="t", description="d", existing_tags=[], transcript=None)

    assert any("repair call failed" in r.message for r in caplog.records)
    # original (still-violating) data is what ships, not a crash
    assert data["tags"] == ["only", "a", "few"]


# ------------------------------------------------------- understand_video (phase 1)


def _understand_response(
    summary="A video about APS certificates for Indian students.",
    audience="Students who have already chosen Germany and are preparing APS documents.",
    next_question="How long does APS verification take?",
):
    response = MagicMock()
    payload = {"content_summary": summary}
    if audience is not None:
        payload["target_audience"] = audience
    if next_question is not None:
        payload["audience_next_question"] = next_question
    response.text = json.dumps(payload)
    return response


@patch("llm.generate_content_with_fallback")
def test_understand_video_returns_all_three_fields(mock_generate):
    mock_generate.return_value = _understand_response(
        "Real summary text.", "Comparison-stage applicants.", "What are the fees?"
    )
    result = understand_video(["k"], title="t", description="d", existing_tags=[], transcript=None)
    assert result.content_summary == "Real summary text."
    assert result.target_audience == "Comparison-stage applicants."
    assert result.audience_next_question == "What are the fees?"


@patch("llm.generate_content_with_fallback")
def test_understand_video_returns_empty_understanding_on_failure(mock_generate):
    mock_generate.side_effect = Exception("boom")
    result = understand_video(["k"], title="t", description="d", existing_tags=[], transcript=None)
    assert result.content_summary == ""
    assert result.target_audience == ""


@patch("llm.generate_content_with_fallback")
def test_understand_video_returns_empty_understanding_on_malformed_response(mock_generate):
    response = MagicMock()
    response.text = "not json"
    mock_generate.return_value = response
    result = understand_video(["k"], title="t", description="d", existing_tags=[], transcript=None)
    assert result.content_summary == ""


@patch("llm.generate_content_with_fallback")
def test_missing_audience_fields_degrade_independently_of_the_summary(mock_generate):
    # A model that returns the summary but omits the audience fields must
    # not cost the caller its content_summary -- the keyword pipeline
    # depends on that one and does not care about the others.
    mock_generate.return_value = _understand_response(
        "Real summary.", audience=None, next_question=None
    )
    result = understand_video(["k"], title="t", description="d", existing_tags=[], transcript=None)
    assert result.content_summary == "Real summary."
    assert result.target_audience == ""
    assert result.audience_next_question == ""


# ------------------------------------------------------ two-phase wiring in generate_seo


@patch("llm.generate_content_with_fallback")
def test_known_content_summary_overrides_whatever_the_model_generated(mock_generate):
    # Deterministic override, not a hint -- even if the model regenerates its
    # own (possibly drifted) summary, phase 1's version must win, since
    # that's the exact text keyword_pipeline.run() already seeded its search
    # off of.
    response = _full_response()
    payload = json.loads(response.text)
    payload["content_summary"] = "model's own drifted summary"
    response.text = json.dumps(payload)
    mock_generate.return_value = response

    data = generate_seo(
        api_keys=["k"], title="t", description="d", existing_tags=[], transcript=None,
        known_content_summary="phase 1's real summary",
    )
    assert data["content_summary"] == "phase 1's real summary"


@patch("llm.generate_content_with_fallback")
def test_no_known_content_summary_lets_the_model_generate_its_own(mock_generate):
    # Planning mode's path: no phase 1 has run, nothing to override with.
    response = _full_response()
    payload = json.loads(response.text)
    payload["content_summary"] = "model generated this itself"
    response.text = json.dumps(payload)
    mock_generate.return_value = response

    data = generate_seo(
        api_keys=["k"], title="t", description="d", existing_tags=[], transcript=None,
    )
    assert data["content_summary"] == "model generated this itself"


@patch("llm.generate_content_with_fallback")
def test_keyword_evidence_is_included_in_the_prompt_sent_to_gemini(mock_generate):
    mock_generate.return_value = _full_response()
    generate_seo(
        api_keys=["k"], title="t", description="d", existing_tags=[], transcript=None,
        keyword_evidence='Real search demand:\n- Primary keyword: "aps certificate germany"',
    )
    sent = mock_generate.call_args.kwargs["contents"]
    assert "Real search demand" in sent
    assert "aps certificate germany" in sent


@patch("llm.generate_content_with_fallback")
def test_target_audience_is_included_in_the_prompt(mock_generate):
    mock_generate.return_value = _full_response()
    generate_seo(
        api_keys=["k"], title="t", description="d", existing_tags=[], transcript=None,
        target_audience="Students who already chose Germany and are comparing universities.",
    )
    sent = mock_generate.call_args.kwargs["contents"]
    assert "Target viewer" in sent
    assert "already chose Germany" in sent


@patch("llm.generate_content_with_fallback")
def test_no_target_audience_means_no_viewer_block_in_the_prompt(mock_generate):
    # "Target viewer" alone isn't a safe marker -- the trailing instructions
    # reference it conditionally whether or not a block was injected. This
    # phrase only appears in the injected block itself.
    mock_generate.return_value = _full_response()
    generate_seo(api_keys=["k"], title="t", description="d", existing_tags=[], transcript=None)
    sent = mock_generate.call_args.kwargs["contents"]
    assert "write for this specific person" not in sent


@patch("llm.generate_content_with_fallback")
def test_no_keyword_evidence_means_no_demand_block_in_the_prompt(mock_generate):
    # "Real search demand" alone isn't a safe marker -- the trailing
    # instructions reference it conditionally regardless of whether a block
    # was actually injected. "Primary keyword:" only appears inside the
    # actual injected block (format_keyword_evidence's output).
    mock_generate.return_value = _full_response()
    generate_seo(api_keys=["k"], title="t", description="d", existing_tags=[], transcript=None)
    sent = mock_generate.call_args.kwargs["contents"]
    assert "Primary keyword:" not in sent
