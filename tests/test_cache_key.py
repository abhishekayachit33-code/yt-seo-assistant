from unittest.mock import patch

from cache_key import compute_fingerprint


def test_same_inputs_produce_same_fingerprint():
    a = compute_fingerprint("Title", "Description", ["b", "a"], "transcript text", ["comment one"])
    b = compute_fingerprint("Title", "Description", ["b", "a"], "transcript text", ["comment one"])
    assert a == b


def test_tag_order_does_not_matter():
    a = compute_fingerprint("Title", "Description", ["a", "b"], None, None)
    b = compute_fingerprint("Title", "Description", ["b", "a"], None, None)
    assert a == b


def test_different_title_changes_fingerprint():
    a = compute_fingerprint("Title A", "Description", [], None, None)
    b = compute_fingerprint("Title B", "Description", [], None, None)
    assert a != b


def test_different_transcript_changes_fingerprint():
    a = compute_fingerprint("Title", "Description", [], "transcript one", None)
    b = compute_fingerprint("Title", "Description", [], "transcript two", None)
    assert a != b


def test_no_transcript_differs_from_empty_string_transcript():
    a = compute_fingerprint("Title", "Description", [], None, None)
    b = compute_fingerprint("Title", "Description", [], "", None)
    assert a == b  # falsy transcript ("" or None) both map to the 'none' marker


def test_different_comments_changes_fingerprint():
    a = compute_fingerprint("Title", "Description", [], None, ["a"])
    b = compute_fingerprint("Title", "Description", [], None, ["b"])
    assert a != b


@patch("cache_key.PROMPT_VERSION", 999)
def test_prompt_version_bump_changes_fingerprint():
    with_current_version = compute_fingerprint("Title", "Description", [], None, None)
    with patch("cache_key.PROMPT_VERSION", 1):
        with_old_version = compute_fingerprint("Title", "Description", [], None, None)
    assert with_current_version != with_old_version
