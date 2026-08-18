from unittest.mock import MagicMock, patch

import pytest
import requests

from deepseek_client import generate_json


def _response(status_code, body=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    if body is not None:
        resp.json.return_value = body
    return resp


@pytest.fixture(autouse=True)
def no_real_sleep():
    with patch("deepseek_client.time.sleep") as mock_sleep:
        yield mock_sleep


@patch("deepseek_client.requests.post")
def test_returns_message_content_on_success(mock_post):
    mock_post.return_value = _response(200, {"choices": [{"message": {"content": '{"a": 1}'}}]})

    result = generate_json(
        api_key="key", model="deepseek-chat", system_prompt="sys", user_prompt="user", schema={},
    )

    assert result == '{"a": 1}'


@patch("deepseek_client.requests.post")
def test_retries_with_backoff_on_transient_error(mock_post, no_real_sleep):
    mock_post.side_effect = [
        _response(503, text="overloaded"),
        _response(503, text="overloaded"),
        _response(200, {"choices": [{"message": {"content": "{}"}}]}),
    ]

    result = generate_json(
        api_key="key", model="deepseek-chat", system_prompt="sys", user_prompt="user", schema={},
    )

    assert result == "{}"
    assert mock_post.call_count == 3
    assert [c.args[0] for c in no_real_sleep.call_args_list] == [1, 2]


@patch("deepseek_client.requests.post")
def test_non_retryable_status_raises_immediately(mock_post, no_real_sleep):
    mock_post.return_value = _response(401, text="invalid api key")

    with pytest.raises(requests.exceptions.HTTPError):
        generate_json(
            api_key="bad-key", model="deepseek-chat", system_prompt="sys", user_prompt="user", schema={},
        )

    mock_post.assert_called_once()
    no_real_sleep.assert_not_called()


@patch("deepseek_client.requests.post")
def test_exhausting_all_retries_raises_last_error(mock_post, no_real_sleep):
    mock_post.return_value = _response(503, text="overloaded")

    with pytest.raises(requests.exceptions.HTTPError):
        generate_json(
            api_key="key", model="deepseek-chat", system_prompt="sys", user_prompt="user", schema={},
        )

    assert mock_post.call_count == 4  # 1 initial + 3 backoff retries


@patch("deepseek_client.requests.post")
def test_network_error_is_retried(mock_post, no_real_sleep):
    mock_post.side_effect = [
        requests.exceptions.ConnectionError("dns failure"),
        _response(200, {"choices": [{"message": {"content": "{}"}}]}),
    ]

    result = generate_json(
        api_key="key", model="deepseek-chat", system_prompt="sys", user_prompt="user", schema={},
    )

    assert result == "{}"
    assert mock_post.call_count == 2
