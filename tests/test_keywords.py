from keywords import estimate_spoken_length


def test_empty_script_returns_none():
    assert estimate_spoken_length("") is None
    assert estimate_spoken_length("   \n  ") is None
    assert estimate_spoken_length(None) is None


def test_typical_script_gives_a_minute_range_not_a_single_number():
    script = " ".join(["word"] * 1400)  # 10 minutes at 140 wpm
    estimate = estimate_spoken_length(script)
    assert estimate.word_count == 1400
    assert estimate.low_minutes < 10 < estimate.high_minutes
    assert estimate.low_minutes != estimate.high_minutes


def test_label_reads_as_an_estimate():
    script = " ".join(["word"] * 1400)
    estimate = estimate_spoken_length(script)
    assert "roughly" in estimate.label
    assert "1,400 words" in estimate.label


def test_short_script_can_collapse_to_a_single_minute_label():
    estimate = estimate_spoken_length("one two three four five")
    assert estimate.word_count == 5
    # Rounds to the same minute at both band edges for a very short script.
    assert "roughly" in estimate.label


def test_custom_wpm_changes_the_estimate():
    script = " ".join(["word"] * 1400)
    slow = estimate_spoken_length(script, wpm=100)
    fast = estimate_spoken_length(script, wpm=200)
    assert slow.low_minutes > fast.low_minutes
