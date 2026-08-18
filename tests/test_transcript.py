from unittest.mock import MagicMock, patch

from youtube_transcript_api import NoTranscriptFound

from transcript import fetch_transcript_segments, segments_to_text


def _snippet(start, duration, text):
    s = MagicMock()
    s.start = start
    s.duration = duration
    s.text = text
    return s


@patch("transcript.YouTubeTranscriptApi")
def test_fetches_english_directly_when_available(mock_api_cls):
    mock_api = MagicMock()
    mock_api.fetch.return_value = [_snippet(0.0, 2.0, "hello")]
    mock_api_cls.return_value = mock_api

    segments = fetch_transcript_segments("vid1")

    assert len(segments) == 1
    assert segments[0].text == "hello"
    mock_api.list.assert_not_called()


@patch("transcript.YouTubeTranscriptApi")
def test_falls_back_to_any_language_when_no_english_transcript(mock_api_cls):
    # Real bug: the old code only ever requested English (the library's
    # default), so a video with only e.g. German captions silently returned
    # None even though a perfectly good transcript existed.
    mock_api = MagicMock()
    mock_api.fetch.side_effect = NoTranscriptFound("vid1", ("en",), MagicMock())
    german_transcript = MagicMock()
    german_transcript.fetch.return_value = [_snippet(0.0, 2.0, "hallo")]
    mock_api.list.return_value = [german_transcript]
    mock_api_cls.return_value = mock_api

    segments = fetch_transcript_segments("vid1")

    assert segments is not None
    assert len(segments) == 1
    assert segments[0].text == "hallo"


@patch("transcript.YouTubeTranscriptApi")
def test_returns_none_when_no_transcript_exists_in_any_language(mock_api_cls):
    mock_api = MagicMock()
    mock_api.fetch.side_effect = NoTranscriptFound("vid1", ("en",), MagicMock())
    mock_api.list.return_value = []
    mock_api_cls.return_value = mock_api

    assert fetch_transcript_segments("vid1") is None


@patch("transcript.YouTubeTranscriptApi")
def test_returns_none_on_any_other_failure(mock_api_cls):
    mock_api = MagicMock()
    mock_api.fetch.side_effect = Exception("network error")
    mock_api_cls.return_value = mock_api

    assert fetch_transcript_segments("vid1") is None


def test_segments_to_text_formats_timestamps():
    segments = [MagicMock(start=65.0, duration=2.0, text="welcome back")]
    text = segments_to_text(segments)
    assert text == "[01:05] welcome back"
