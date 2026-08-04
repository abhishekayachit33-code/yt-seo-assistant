from limits import DESCRIPTION_MAX, HASHTAGS_MAX, TAGS_MAX, TITLE_MAX, check_limits


def test_all_under_limit_are_ok():
    checks = check_limits("short title", "short description", ["a", "b"], ["#a", "#b"])
    assert all(c.ok for c in checks)


def test_title_over_limit_flagged():
    checks = check_limits("x" * (TITLE_MAX + 1), "", [], [])
    title_check = next(c for c in checks if c.label == "Title")
    assert not title_check.ok
    assert title_check.current == TITLE_MAX + 1


def test_title_at_exact_limit_is_ok():
    checks = check_limits("x" * TITLE_MAX, "", [], [])
    title_check = next(c for c in checks if c.label == "Title")
    assert title_check.ok


def test_description_over_limit_flagged():
    checks = check_limits("", "x" * (DESCRIPTION_MAX + 1), [], [])
    desc_check = next(c for c in checks if c.label == "Description")
    assert not desc_check.ok


def test_tags_combined_characters_over_limit():
    tags = ["x" * 100] * 10  # 100*10 + 9 separators of ", " = 1018 chars
    checks = check_limits("", "", tags, [])
    tags_check = next(c for c in checks if "Tags" in c.label)
    assert not tags_check.ok
    assert tags_check.maximum == TAGS_MAX


def test_hashtags_over_count_limit():
    hashtags = [f"#tag{i}" for i in range(HASHTAGS_MAX + 1)]
    checks = check_limits("", "", [], hashtags)
    hashtag_check = next(c for c in checks if "Hashtag" in c.label)
    assert not hashtag_check.ok
    assert hashtag_check.current == HASHTAGS_MAX + 1
