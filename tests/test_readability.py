from readability import scan_readability


def test_empty_script_returns_none():
    assert scan_readability("") is None
    assert scan_readability("   ") is None
    assert scan_readability(None) is None


def test_counts_filler_words():
    script = "So, um, this is like, you know, a test. It works, actually."
    report = scan_readability(script)
    words = {h.word: h.count for h in report.filler_hits}
    assert words["um"] == 1
    assert words["like"] == 1
    assert words["you know"] == 1
    assert words["so"] == 1
    assert words["actually"] == 1
    assert report.total_filler_count == sum(words.values())


def test_filler_rate_is_per_hundred_words():
    script = "um " * 10 + "word " * 90  # 10 fillers in 100 words
    report = scan_readability(script)
    assert report.word_count == 100
    assert report.filler_rate == 10.0


def test_no_filler_words_reports_empty_hits():
    report = scan_readability("This is a clean script with no filler content at all.")
    assert report.filler_hits == []
    assert report.total_filler_count == 0


def test_sentence_splitting_and_average_length():
    report = scan_readability("One two three. Four five six seven eight.")
    assert report.sentence_count == 2
    assert report.word_count == 8  # \S+ tokens, punctuation stays attached
    assert report.avg_sentence_length == 4.0


def test_strips_transcript_timestamps_before_counting():
    report = scan_readability("[00:00] Hello there. [00:15] General Kenobi.")
    assert report.word_count == 4  # timestamps not counted as words


def test_filler_matching_is_word_boundary_not_substring():
    # "sole" contains "so" as a substring but must not match the filler "so".
    report = scan_readability("This is the sole reason we did this.")
    assert not any(h.word == "so" for h in report.filler_hits)
