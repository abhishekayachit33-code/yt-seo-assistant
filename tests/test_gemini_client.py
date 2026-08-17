from unittest.mock import MagicMock, patch

import pytest
from google.genai import errors

from gemini_client import generate_content_with_fallback


def _quota_error():
    return errors.APIError(429, {"error": {"message": "quota exceeded", "status": "RESOURCE_EXHAUSTED"}}, None)


def _overloaded_error():
    return errors.APIError(503, {"error": {"message": "high demand", "status": "UNAVAILABLE"}}, None)


def _other_error():
    return errors.APIError(400, {"error": {"message": "bad request", "status": "INVALID_ARGUMENT"}}, None)


@pytest.fixture(autouse=True)
def no_real_sleep():
    with patch("gemini_client.time.sleep") as mock_sleep:
        yield mock_sleep


@patch("gemini_client.genai.Client")
def test_falls_back_to_second_key_on_quota_error(mock_client_cls):
    sentinel_response = MagicMock()
    first_client = MagicMock()
    first_client.models.generate_content.side_effect = _quota_error()
    second_client = MagicMock()
    second_client.models.generate_content.return_value = sentinel_response
    mock_client_cls.side_effect = [first_client, second_client]

    result = generate_content_with_fallback(["key1", "key2"], model="m", contents="hi")

    assert result is sentinel_response
    assert mock_client_cls.call_args_list[0].kwargs == {"api_key": "key1"}
    assert mock_client_cls.call_args_list[1].kwargs == {"api_key": "key2"}


@patch("gemini_client.genai.Client")
def test_falls_back_to_second_key_on_service_unavailable(mock_client_cls):
    """503 (Google backend overloaded) found live -- a real analysis hit this
    after both keys' 429/404 paths were already fixed. Worth retrying against
    a different key/project, unlike a fixed problem with the request itself."""
    sentinel_response = MagicMock()
    first_client = MagicMock()
    first_client.models.generate_content.side_effect = _overloaded_error()
    second_client = MagicMock()
    second_client.models.generate_content.return_value = sentinel_response
    mock_client_cls.side_effect = [first_client, second_client]

    result = generate_content_with_fallback(["key1", "key2"], model="m", contents="hi")

    assert result is sentinel_response


@patch("gemini_client.genai.Client")
def test_raises_last_error_when_all_keys_exhausted(mock_client_cls):
    client = MagicMock()
    client.models.generate_content.side_effect = _quota_error()
    mock_client_cls.return_value = client

    with pytest.raises(errors.APIError) as exc_info:
        generate_content_with_fallback(["key1", "key2"], model="m", contents="hi")
    assert exc_info.value.code == 429


@patch("gemini_client.genai.Client")
def test_non_quota_error_raises_immediately_without_trying_next_key(mock_client_cls):
    first_client = MagicMock()
    first_client.models.generate_content.side_effect = _other_error()
    second_client = MagicMock()
    mock_client_cls.side_effect = [first_client, second_client]

    with pytest.raises(errors.APIError) as exc_info:
        generate_content_with_fallback(["key1", "key2"], model="m", contents="hi")

    assert exc_info.value.code == 400
    second_client.models.generate_content.assert_not_called()


def test_no_keys_raises_value_error():
    with pytest.raises(ValueError):
        generate_content_with_fallback([], model="m", contents="hi")


def test_falsy_keys_are_filtered_out():
    with pytest.raises(ValueError):
        generate_content_with_fallback([None, "", None], model="m", contents="hi")


@patch("gemini_client.genai.Client")
def test_retries_same_key_with_backoff_before_moving_on(mock_client_cls, no_real_sleep):
    # A real 503 clears within a few seconds -- failing the whole run after
    # one instant attempt throws away runs a short wait would have saved.
    sentinel_response = MagicMock()
    first_client = MagicMock()
    first_client.models.generate_content.side_effect = [
        _overloaded_error(), _overloaded_error(), sentinel_response,
    ]
    mock_client_cls.return_value = first_client

    result = generate_content_with_fallback(["key1"], model="m", contents="hi")

    assert result is sentinel_response
    assert first_client.models.generate_content.call_count == 3
    # Backoff before the 2nd and 3rd attempts, increasing delay.
    assert [c.args[0] for c in no_real_sleep.call_args_list] == [1, 2]


@patch("gemini_client.genai.Client")
def test_exhausting_retries_on_first_key_still_falls_back_to_second(mock_client_cls, no_real_sleep):
    sentinel_response = MagicMock()
    first_client = MagicMock()
    first_client.models.generate_content.side_effect = _overloaded_error()
    second_client = MagicMock()
    second_client.models.generate_content.return_value = sentinel_response
    mock_client_cls.side_effect = [first_client, second_client]

    result = generate_content_with_fallback(["key1", "key2"], model="m", contents="hi")

    assert result is sentinel_response
    # 1 initial + 3 backoff retries exhausted on key1 before key2 is tried.
    assert first_client.models.generate_content.call_count == 4
    second_client.models.generate_content.assert_called_once()


@patch("gemini_client.genai.Client")
def test_non_retryable_error_does_not_sleep(mock_client_cls, no_real_sleep):
    client = MagicMock()
    client.models.generate_content.side_effect = _other_error()
    mock_client_cls.return_value = client

    with pytest.raises(errors.APIError):
        generate_content_with_fallback(["key1"], model="m", contents="hi")

    no_real_sleep.assert_not_called()
