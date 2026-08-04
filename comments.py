import json

import requests
from google import genai
from google.genai import types

from llm import MODEL

_ENDPOINT = "https://www.googleapis.com/youtube/v3/commentThreads"

_SUMMARY_SYSTEM_PROMPT = (
    "You are summarizing YouTube comments for a creator. Given a list of "
    "top-level comments, identify what viewers praised and what they "
    "complained about. Be specific -- reference actual themes in the "
    "comments, not generic observations. If comments are overwhelmingly "
    "positive or negative, it is fine for one list to be empty."
)

_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "positive_themes": {"type": "array", "items": {"type": "string"}},
        "negative_themes": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
    "required": ["positive_themes", "negative_themes", "summary"],
}


def fetch_top_comments(video_id: str, api_key: str, max_results: int = 50) -> list[str]:
    """Top-level comment text, ranked by relevance. Empty list if comments are
    disabled or unavailable -- never raises for that case, same pattern as
    fetch_transcript_text()."""
    try:
        response = requests.get(
            _ENDPOINT,
            params={
                "part": "snippet",
                "videoId": video_id,
                "order": "relevance",
                "maxResults": max_results,
                "textFormat": "plainText",
                "key": api_key,
            },
            timeout=10,
        )
        response.raise_for_status()
    except requests.exceptions.HTTPError:
        return []

    items = response.json().get("items", [])
    return [
        item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
        for item in items
    ]


def summarize_comments(api_key: str, comments: list[str]) -> dict:
    """One Gemini call over already-fetched comment text. Returns empty
    themes with no summary if there's nothing to summarize, or if the call
    itself fails (rate limit, quota, network) -- comment sentiment is a
    nice-to-have layered on core analysis and must never crash the page."""
    empty = {"positive_themes": [], "negative_themes": [], "summary": ""}
    if not comments:
        return empty

    try:
        client = genai.Client(api_key=api_key)
        numbered = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(comments))

        response = client.models.generate_content(
            model=MODEL,
            contents=f"Comments:\n{numbered}",
            config=types.GenerateContentConfig(
                system_instruction=_SUMMARY_SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=_SUMMARY_SCHEMA,
                temperature=0.4,
            ),
        )
        data = json.loads(response.text)
    except Exception:
        return empty

    data.setdefault("positive_themes", [])
    data.setdefault("negative_themes", [])
    data.setdefault("summary", "")
    return data
