from google import genai
from google.genai import errors

QUOTA_EXCEEDED_CODE = 429


def generate_content_with_fallback(api_keys: list[str], **kwargs):
    """Calls generate_content, trying each key in order. On a 429 (quota
    exhausted) moves to the next key; any other error raises immediately,
    since retrying a bad request with a different key won't fix it."""
    keys = [k for k in api_keys if k]
    if not keys:
        raise ValueError("No Gemini API keys configured")

    last_exc = None
    for key in keys:
        client = genai.Client(api_key=key)
        try:
            return client.models.generate_content(**kwargs)
        except errors.APIError as exc:
            if exc.code == QUOTA_EXCEEDED_CODE:
                last_exc = exc
                continue
            raise

    raise last_exc
