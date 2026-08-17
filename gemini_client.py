import logging
import time

from google import genai
from google.genai import errors

logger = logging.getLogger(__name__)

QUOTA_EXCEEDED_CODE = 429
SERVICE_UNAVAILABLE_CODE = 503

# Errors worth trying a different key/project for. 429 is quota exhaustion on
# this specific key; 503 is Google's backend reporting transient overload,
# where a different key might land on different capacity. Anything else
# (400 bad request, 404 model not found, 403 permission denied) is a fixed
# property of the request or the key itself -- a different key won't fix it.
_RETRYABLE_CODES = {QUOTA_EXCEEDED_CODE, SERVICE_UNAVAILABLE_CODE}

# Backoff between retries on the SAME key before moving to the next one.
# 503 (Google-side overload, "high demand, try again later") often clears
# within a few seconds; failing after a single instant attempt throws away
# runs that a few seconds' wait would have saved. 429 (quota) won't clear
# this fast, but retrying it costs nothing extra since the next key is tried
# immediately after regardless.
_RETRY_DELAYS_SECONDS = [1, 2, 4]


def generate_content_with_fallback(api_keys: list[str], **kwargs):
    """Calls generate_content, retrying each key with backoff on a retryable
    error (429 quota, 503 overloaded) before moving to the next key; any
    other error raises immediately, since retrying a bad request won't fix
    it. Every attempt is logged (key position, not the key itself, plus the
    error code) so a run that exhausts all keys says exactly what each key
    hit instead of only the last one's exception."""
    keys = [k for k in api_keys if k]
    if not keys:
        raise ValueError("No Gemini API keys configured")

    last_exc = None
    total_attempts = len(_RETRY_DELAYS_SECONDS) + 1
    for key_index, key in enumerate(keys, start=1):
        client = genai.Client(api_key=key)
        for attempt, delay in enumerate([0, *_RETRY_DELAYS_SECONDS], start=1):
            if delay:
                time.sleep(delay)
            try:
                return client.models.generate_content(**kwargs)
            except errors.APIError as exc:
                last_exc = exc
                if exc.code not in _RETRYABLE_CODES:
                    logger.warning(
                        "gemini call failed on key %d/%d, not retryable: %d %s",
                        key_index, len(keys), exc.code, exc.status,
                    )
                    raise
                logger.warning(
                    "gemini call failed (key %d/%d, attempt %d/%d): %d %s",
                    key_index, len(keys), attempt, total_attempts, exc.code, exc.status,
                )

    raise last_exc
