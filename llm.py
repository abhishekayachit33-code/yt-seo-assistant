import json

from google import genai
from google.genai import types

MODEL = "gemini-2.5-flash"

SYSTEM_PROMPT = (
    "You are an SEO assistant for YouTube creators. Given a video's title, "
    "description, existing tags, and transcript (if available), produce SEO "
    "assistance for that exact video.\n"
    "Rules:\n"
    "- tags: at least 35 relevant, specific SEO keywords/phrases for this exact video.\n"
    "- chapters: only include if a transcript was provided; first chapter must be "
    '"00:00"; timestamps strictly increasing; base them on real topic shifts in '
    "the transcript. If no transcript was provided, return an empty list.\n"
    "- suggestions: actionable, specific ideas to improve this video's reach and "
    "content, not generic advice."
)

SEO_SCHEMA = {
    "type": "object",
    "properties": {
        "tags": {"type": "array", "items": {"type": "string"}},
        "chapters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "timestamp": {"type": "string"},
                    "title": {"type": "string"},
                },
                "required": ["timestamp", "title"],
            },
        },
        "suggestions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["tags", "chapters", "suggestions"],
}


def _build_user_prompt(title: str, description: str, existing_tags: list[str], transcript: str | None) -> str:
    parts = [
        f"Title: {title}",
        f"Existing tags: {', '.join(existing_tags) if existing_tags else '(none)'}",
        f"Description:\n{description[:2000]}",
    ]
    if transcript:
        parts.append(f"Transcript:\n{transcript}")
    else:
        parts.append("Transcript: (not available for this video)")
    return "\n\n".join(parts)


def generate_seo(
    api_key: str,
    title: str,
    description: str,
    existing_tags: list[str],
    transcript: str | None,
) -> dict:
    client = genai.Client(api_key=api_key)
    user_prompt = _build_user_prompt(title, description, existing_tags, transcript)

    response = client.models.generate_content(
        model=MODEL,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=SEO_SCHEMA,
            temperature=0.4,
        ),
    )
    raw = response.text

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model did not return valid JSON: {exc}\nRaw: {raw[:500]}") from exc

    data.setdefault("tags", [])
    data.setdefault("chapters", [])
    data.setdefault("suggestions", [])
    return data
