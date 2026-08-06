from cta import LATE, TOO_EARLY, TOO_LATE, WELL_PLACED, analyze_ctas, zone_for
from transcript import TranscriptSegment


def video(lines: list[tuple[float, str]], total: float = 600.0) -> list[TranscriptSegment]:
    """Transcript segments plus a trailing silent segment that fixes runtime."""
    segments = [TranscriptSegment(start=t, duration=3.0, text=text) for t, text in lines]
    segments.append(TranscriptSegment(start=total - 3, duration=3.0, text="goodbye"))
    return segments


def test_zone_boundaries():
    assert zone_for(0.0) == TOO_EARLY
    assert zone_for(0.04) == TOO_EARLY
    assert zone_for(0.05) == WELL_PLACED
    assert zone_for(0.70) == WELL_PLACED
    assert zone_for(0.71) == LATE
    assert zone_for(0.90) == LATE
    assert zone_for(0.95) == TOO_LATE


def test_end_of_video_subscribe_is_flagged_too_late():
    report = analyze_ctas(video([(570, "so please subscribe to the channel")], total=600))
    (mention,) = report.mentions
    assert mention.zone == TOO_LATE
    assert mention.timestamp == "09:30"
    assert mention.label == "subscribe"
    assert report.stranded == [mention]
    assert not report.has_well_placed


def test_mid_video_cta_is_well_placed():
    report = analyze_ctas(video([(300, "subscribe if this helped")], total=600))
    assert report.mentions[0].zone == WELL_PLACED
    assert report.has_well_placed
    assert report.stranded == []


def test_cta_before_any_value_is_too_early():
    report = analyze_ctas(video([(5, "subscribe right now")], total=600))
    assert report.mentions[0].zone == TOO_EARLY


def test_recommended_mark_sits_in_the_prime_window():
    report = analyze_ctas(video([(570, "subscribe")], total=600))
    assert report.recommended_timestamp == "03:30"
    assert zone_for(report.recommended_seconds / report.duration) == WELL_PLACED


def test_various_cta_phrasings_are_detected():
    report = analyze_ctas(
        video(
            [
                (60, "the link in the description has everything"),
                (120, "use my code to get started"),
                (180, "let me know in the comments"),
                (240, "join our discord"),
            ],
            total=600,
        )
    )
    assert {m.label for m in report.mentions} == {
        "link in description", "discount code", "comment below", "join",
    }


def test_line_with_several_asks_counts_once():
    report = analyze_ctas(video([(300, "subscribe and check it out and sign up")], total=600))
    assert len(report.mentions) == 1


def test_transcript_with_no_asks_returns_empty_report():
    report = analyze_ctas(video([(100, "today we are baking bread")], total=600))
    assert report.mentions == []
    assert not report.has_well_placed


def test_no_transcript_returns_none():
    assert analyze_ctas(None) is None
    assert analyze_ctas([]) is None


def test_ordinary_words_do_not_trigger_false_matches():
    report = analyze_ctas(
        video([(100, "I unlike bells and belligerent joining of tables")], total=600)
    )
    assert [m.label for m in report.mentions] == []
