from limits import TAGS_MAX
from llm import MIN_TAGS, enforce_tag_char_limit, find_output_violations


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
