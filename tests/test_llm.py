from llm import MIN_TAGS, find_output_violations


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
