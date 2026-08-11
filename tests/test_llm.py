import json
from unittest.mock import MagicMock, patch

from limits import TAGS_MAX
from llm import MIN_TAGS, enforce_tag_char_limit, find_output_violations, generate_seo


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
