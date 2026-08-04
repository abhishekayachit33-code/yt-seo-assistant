from google import genai
from google.genai import errors

QUOTA_EXCEEDED_CODE = 429
SERVICE_UNAVAILABLE_CODE = 503

# Errors worth trying a different key/project for. 429 is quota exhaustion on
# this specific key; 503 is Google's backend reporting transient overload,
# where a different key might land on different capacity. Anything else
# (400 bad request, 404 model not found, 403 permission denied) is a fixed
# property of the request or the key itself -- a different key won't fix it.
_RETRYABLE_CODES = {QUOTA_EXCEEDED_CODE, SERVICE_UNAVAILABLE_CODE}


def generate_content_with_fallback(api_keys: list[str], **kwargs):
    """Calls generate_content, trying each key in order on a retryable error
    (429 quota, 503 overloaded); any other error raises immediately, since
    retrying a bad request with a different key won't fix it."""
    keys = [k for k in api_keys if k]
    if not keys:
        raise ValueError("No Gemini API keys configured")

    last_exc = None
    for key in keys:
        client = genai.Client(api_key=key)
        try:
            return client.models.generate_content(**kwargs)
        except errors.APIError as exc:
            if exc.code in _RETRYABLE_CODES:
                last_exc = exc
                continue
            raise

    raise last_exc
