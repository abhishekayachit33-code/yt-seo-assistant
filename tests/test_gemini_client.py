from unittest.mock import MagicMock, patch

import pytest
from google.genai import errors

from gemini_client import generate_content_with_fallback


def _quota_error():
    return errors.APIError(429, {"error": {"message": "quota exceeded", "status": "RESOURCE_EXHAUSTED"}}, None)


def _other_error():
    return errors.APIError(400, {"error": {"message": "bad request", "status": "INVALID_ARGUMENT"}}, None)


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
