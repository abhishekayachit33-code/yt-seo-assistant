from unittest.mock import MagicMock, patch

from google.genai import types

from llm import _generate_json


def _config():
    return types.GenerateContentConfig(
        system_instruction="sys", response_mime_type="application/json",
        response_schema={"type": "object"}, temperature=0.4,
    )


@patch("llm.generate_content_with_fallback")
@patch("llm._deepseek_generate_json")
def test_no_deepseek_key_goes_straight_to_gemini(mock_deepseek, mock_gemini):
    sentinel = MagicMock()
    mock_gemini.return_value = sentinel

    result = _generate_json(["gkey"], model="gemini-flash-latest", contents="hi", config=_config())

    assert result is sentinel
    mock_deepseek.assert_not_called()
    mock_gemini.assert_called_once()


@patch("llm.generate_content_with_fallback")
@patch("llm._deepseek_generate_json")
def test_deepseek_success_skips_gemini_entirely(mock_deepseek, mock_gemini):
    mock_deepseek.return_value = '{"ok": true}'

    result = _generate_json(
        ["gkey"], model="gemini-flash-latest", contents="hi", config=_config(),
        deepseek_api_key="dkey",
    )

    assert result.text == '{"ok": true}'
    mock_gemini.assert_not_called()


@patch("llm.generate_content_with_fallback")
@patch("llm._deepseek_generate_json")
def test_deepseek_failure_falls_back_to_gemini(mock_deepseek, mock_gemini):
    mock_deepseek.side_effect = Exception("deepseek down")
    sentinel = MagicMock()
    mock_gemini.return_value = sentinel

    result = _generate_json(
        ["gkey"], model="gemini-flash-latest", contents="hi", config=_config(),
        deepseek_api_key="dkey",
    )

    assert result is sentinel
    mock_gemini.assert_called_once()


@patch("llm.generate_content_with_fallback")
@patch("llm._deepseek_generate_json")
def test_deepseek_call_uses_config_fields(mock_deepseek, mock_gemini):
    mock_deepseek.return_value = "{}"

    _generate_json(
        ["gkey"], model="gemini-flash-latest", contents="user text", config=_config(),
        deepseek_api_key="dkey",
    )

    kwargs = mock_deepseek.call_args.kwargs
    assert kwargs["api_key"] == "dkey"
    assert kwargs["system_prompt"] == "sys"
    assert kwargs["user_prompt"] == "user text"
    assert kwargs["schema"] == {"type": "object"}
    assert kwargs["temperature"] == 0.4
