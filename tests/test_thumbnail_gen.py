import json
from unittest.mock import MagicMock, patch

import requests

from thumbnail_gen import generate_thumbnail_image, generate_thumbnail_prompts

FAKE_CONCEPTS = {
    "concepts": [
        {"label": "Bold close-up", "prompt": "a dramatic close-up, high contrast"},
        {"label": "Wide establishing shot", "prompt": "a wide cinematic shot, cool tones"},
    ]
}


def _fake_response():
    response = MagicMock()
    response.text = json.dumps(FAKE_CONCEPTS)
    return response


@patch("thumbnail_gen.generate_content_with_fallback")
def test_generate_thumbnail_prompts_returns_parsed_concepts(mock_generate):
    mock_generate.return_value = _fake_response()
    result = generate_thumbnail_prompts(["k"], "My Title", "some context", count=3)
    assert result == FAKE_CONCEPTS["concepts"]


@patch("thumbnail_gen.generate_content_with_fallback")
def test_generate_thumbnail_prompts_truncates_to_count(mock_generate):
    mock_generate.return_value = _fake_response()
    result = generate_thumbnail_prompts(["k"], "My Title", "some context", count=1)
    assert len(result) == 1


@patch("thumbnail_gen.generate_content_with_fallback")
def test_generate_thumbnail_prompts_returns_empty_on_failure(mock_generate):
    mock_generate.side_effect = Exception("boom")
    assert generate_thumbnail_prompts(["k"], "My Title", "context") == []


def test_generate_thumbnail_image_empty_key_returns_none_without_calling_huggingface():
    assert generate_thumbnail_image("", "a prompt") is None


def test_generate_thumbnail_image_empty_prompt_returns_none():
    assert generate_thumbnail_image("key", "") is None


def _prediction_response(status, output=None, get_url="https://api.replicate.com/v1/predictions/abc"):
    resp = MagicMock()
    resp.raise_for_status = lambda: None
    resp.json.return_value = {
        "status": status,
        "output": output,
        "urls": {"get": get_url},
    }
    return resp


@patch("thumbnail_gen.requests.get")
@patch("thumbnail_gen.requests.post")
def test_generate_thumbnail_image_returns_bytes_when_wait_resolves_inline(mock_post, mock_get):
    mock_post.return_value = _prediction_response("succeeded", output="https://replicate.delivery/img.webp")
    image_response = MagicMock()
    image_response.content = b"fake-image-bytes"
    image_response.raise_for_status = lambda: None
    mock_get.return_value = image_response

    result = generate_thumbnail_image("secret-token", "a dramatic scene")

    assert result == b"fake-image-bytes"
    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer secret-token"
    assert kwargs["headers"]["Prefer"] == "wait"
    assert kwargs["json"]["input"]["prompt"] == "a dramatic scene"
    assert kwargs["json"]["input"]["aspect_ratio"] == "16:9"
    # only the final image fetch hits requests.get -- no polling needed
    mock_get.assert_called_once_with("https://replicate.delivery/img.webp", timeout=30)


@patch("thumbnail_gen.time.sleep")
@patch("thumbnail_gen.requests.get")
@patch("thumbnail_gen.requests.post")
def test_generate_thumbnail_image_polls_when_still_processing(mock_post, mock_get, mock_sleep):
    mock_post.return_value = _prediction_response("processing")
    poll_pending = _prediction_response("processing")
    poll_done = _prediction_response("succeeded", output="https://replicate.delivery/img.webp")
    image_response = MagicMock()
    image_response.content = b"fake-image-bytes"
    image_response.raise_for_status = lambda: None
    mock_get.side_effect = [poll_pending, poll_done, image_response]

    result = generate_thumbnail_image("secret-token", "a dramatic scene")

    assert result == b"fake-image-bytes"
    assert mock_get.call_count == 3


@patch("thumbnail_gen.requests.post")
def test_generate_thumbnail_image_returns_none_on_failed_status(mock_post):
    mock_post.return_value = _prediction_response("failed")
    assert generate_thumbnail_image("secret-token", "a dramatic scene") is None


@patch("thumbnail_gen.requests.post")
def test_generate_thumbnail_image_returns_none_on_request_failure(mock_post):
    mock_post.side_effect = requests.exceptions.RequestException("network error")
    assert generate_thumbnail_image("secret-token", "a dramatic scene") is None
