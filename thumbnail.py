import json

import requests
from google import genai
from google.genai import types

from llm import MODEL

_SYSTEM_PROMPT = (
    "You are a YouTube thumbnail critic. Given a thumbnail image, assess: "
    "whether any text on it stays legible at small (mobile feed) size, "
    "whether there is a clear focal point, and whether it would stand out "
    "against a busy subscription feed. Be specific about what you actually "
    "see in the image, not generic thumbnail advice."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "legible_at_small_size": {"type": "boolean"},
        "has_clear_focal_point": {"type": "boolean"},
        "stands_out_in_feed": {"type": "boolean"},
        "feedback": {"type": "string"},
    },
    "required": [
        "legible_at_small_size", "has_clear_focal_point",
        "stands_out_in_feed", "feedback",
    ],
}


def critique_thumbnail(api_key: str, thumbnail_url: str) -> dict | None:
    """Fetches the thumbnail and sends it to Gemini for critique. Returns None
    on any failure -- this is a nice-to-have, never worth breaking the rest
    of the analysis over."""
    if not thumbnail_url:
        return None

    try:
        image_response = requests.get(thumbnail_url, timeout=10)
        image_response.raise_for_status()
    except requests.exceptions.RequestException:
        return None

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=MODEL,
            contents=[
                types.Part.from_bytes(data=image_response.content, mime_type="image/jpeg"),
                "Critique this YouTube thumbnail.",
            ],
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=_SCHEMA,
                temperature=0.4,
            ),
        )
        return json.loads(response.text)
    except Exception:
        return None
