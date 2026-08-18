import logging
import time

import requests

logger = logging.getLogger(__name__)

DEEPSEEK_CHAT_URL = "https://api.deepseek.com/chat/completions"

# Same retryable-error philosophy as gemini_client.py: 429 (rate limit) and
# 5xx (transient backend trouble) are worth a short backoff retry; anything
# else (401/400/...) is a fixed property of the request/key and a wait
# won't fix it.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_RETRY_DELAYS_SECONDS = [1, 2, 4]


def generate_json(
    api_key: str, model: str, system_prompt: str, user_prompt: str,
    schema: dict, temperature: float = 0.4, timeout: int = 60,
) -> str:
    """Calls DeepSeek's OpenAI-compatible chat completions endpoint in JSON
    mode, retrying with backoff on rate-limit/transient errors, mirroring
    gemini_client.generate_content_with_fallback's retry shape.

    DeepSeek's json_object response mode guarantees syntactically valid
    JSON but -- unlike Gemini's response_schema -- does not enforce a
    specific shape. The schema is embedded in the prompt as guidance
    instead; callers already run a structural repair pass (llm.repair_output)
    regardless of which provider answered, so this is not a new risk, just
    a slightly higher chance of needing that existing repair pass.

    Returns the raw JSON text (unparsed) so callers use it exactly like
    a Gemini response's `.text`. Raises on failure -- callers decide
    whether to fall back to another provider.
    """
    schema_hint = (
        "Respond with ONLY a single JSON object (no markdown fences, no "
        "commentary) matching this JSON Schema:\n" + str(schema)
    )
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{user_prompt}\n\n{schema_hint}"},
        ],
        "response_format": {"type": "json_object"},
        "temperature": temperature,
    }

    last_exc: Exception | None = None
    total_attempts = len(_RETRY_DELAYS_SECONDS) + 1
    for attempt, delay in enumerate([0, *_RETRY_DELAYS_SECONDS], start=1):
        if delay:
            time.sleep(delay)
        try:
            resp = requests.post(DEEPSEEK_CHAT_URL, headers=headers, json=payload, timeout=timeout)
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            logger.warning(
                "deepseek call failed (attempt %d/%d): network error: %s",
                attempt, total_attempts, exc,
            )
            continue

        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]

        last_exc = requests.exceptions.HTTPError(f"{resp.status_code}: {resp.text[:300]}")
        if resp.status_code not in _RETRYABLE_STATUS:
            logger.warning(
                "deepseek call failed, not retryable: %d %s", resp.status_code, resp.text[:200],
            )
            raise last_exc
        logger.warning(
            "deepseek call failed (attempt %d/%d): %d", attempt, total_attempts, resp.status_code,
        )

    raise last_exc
