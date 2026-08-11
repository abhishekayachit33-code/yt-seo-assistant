import json
from unittest.mock import MagicMock, patch

from thumbnail import critique_thumbnail, critique_thumbnail_bytes

FAKE_CRITIQUE = {
    "legible_at_small_size": True,
    "has_clear_focal_point": True,
    "stands_out_in_feed": False,
    "feedback": "Good contrast, busy background.",
}


def _fake_response():
    response = MagicMock()
    response.text = json.dumps(FAKE_CRITIQUE)
    return response


def test_critique_thumbnail_bytes_empty_returns_none_without_calling_gemini():
    assert critique_thumbnail_bytes(["k"], b"") is None


@patch("thumbnail.generate_content_with_fallback")
def test_critique_thumbnail_bytes_returns_parsed_result(mock_generate):
    mock_generate.return_value = _fake_response()
    result = critique_thumbnail_bytes(["k"], b"fake-image-bytes", "image/png")
    assert result == FAKE_CRITIQUE
    assert mock_generate.call_args.kwargs["contents"][0].inline_data.mime_type == "image/png"


@patch("thumbnail.generate_content_with_fallback")
def test_critique_thumbnail_bytes_returns_none_on_gemini_failure(mock_generate):
    mock_generate.side_effect = Exception("boom")
    assert critique_thumbnail_bytes(["k"], b"fake-image-bytes") is None


def test_critique_thumbnail_empty_url_returns_none():
    assert critique_thumbnail(["k"], "") is None


@patch("thumbnail.critique_thumbnail_bytes")
@patch("thumbnail.requests.get")
def test_critique_thumbnail_fetches_url_then_delegates_to_bytes(mock_get, mock_bytes_critique):
    image_response = MagicMock()
    image_response.content = b"fetched-bytes"
    image_response.raise_for_status = lambda: None
    mock_get.return_value = image_response
    mock_bytes_critique.return_value = FAKE_CRITIQUE

    result = critique_thumbnail(["k"], "https://example.com/thumb.jpg")

    assert result == FAKE_CRITIQUE
    mock_bytes_critique.assert_called_once_with(["k"], b"fetched-bytes", "image/jpeg")


@patch("thumbnail.requests.get")
def test_critique_thumbnail_returns_none_on_fetch_failure(mock_get):
    import requests
    mock_get.side_effect = requests.exceptions.RequestException("network error")
    assert critique_thumbnail(["k"], "https://example.com/thumb.jpg") is None
