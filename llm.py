import json
from dataclasses import dataclass

from google.genai import types

from gemini_client import generate_content_with_fallback

MODEL = "gemini-flash-latest"

SYSTEM_PROMPT = (
    "You are an SEO assistant for YouTube creators. Given a video's title, "
    "description, existing tags, and transcript (if available), produce SEO "
    "assistance for that exact video.\n"
    "Rules:\n"
    "- tags: at least 35 relevant, specific SEO keywords/phrases for this exact video.\n"
    "- chapters: only include if a transcript was provided; first chapter must be "
    '"00:00"; timestamps strictly increasing, each at least 10 seconds apart; base '
    "them on real topic shifts in the transcript. If no transcript was provided, "
    "return an empty list.\n"
    "- suggestions: actionable, specific ideas to improve this video's reach and "
    "content, not generic advice.\n"
    "- titles: 5 alternative optimized titles for this video, each under 100 characters.\n"
    "- description: a full optimized video description, folding in the chapter "
    "timestamps if any, ending with a natural call-to-action.\n"
    "- hashtags: 10-15 hashtags (with # prefix), distinct from the tags list, "
    "suited to appear above the title on YouTube.\n"
    "- hook_analysis: judge only the first ~30 seconds of the transcript (if "
    "available) on whether it hooks a viewer fast enough. If no transcript is "
    'available, set verdict to "unavailable" and leave reasoning and rewrite empty.'
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
        "titles": {"type": "array", "items": {"type": "string"}},
        "description": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "hook_analysis": {
            "type": "object",
            "properties": {
                "verdict": {"type": "string"},
                "reasoning": {"type": "string"},
                "rewrite": {"type": "string"},
            },
            "required": ["verdict", "reasoning", "rewrite"],
        },
    },
    "required": [
        "tags", "chapters", "suggestions", "titles",
        "description", "hashtags", "hook_analysis",
    ],
}

MIN_TAGS = 35
MIN_CHAPTER_GAP_SECONDS = 10


@dataclass
class Violation:
    field: str
    reason: str


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


def _timestamp_to_seconds(ts: str) -> int | None:
    parts = ts.split(":")
    if not all(p.isdigit() for p in parts):
        return None
    seconds = 0
    for p in parts:
        seconds = seconds * 60 + int(p)
    return seconds


def find_output_violations(data: dict, has_transcript: bool) -> list[Violation]:
    """Pure check of the model's output against the brief's hard requirements. No I/O."""
    violations = []

    tags = data.get("tags", [])
    if len(tags) < MIN_TAGS:
        violations.append(Violation("tags", f"only {len(tags)} tags, need at least {MIN_TAGS}"))

    chapters = data.get("chapters", [])
    if not has_transcript and chapters:
        violations.append(Violation("chapters", "chapters present but no transcript was available"))
    elif has_transcript and chapters:
        if chapters[0].get("timestamp") != "00:00":
            violations.append(Violation("chapters", "first chapter is not 00:00"))
        prev = None
        for c in chapters:
            secs = _timestamp_to_seconds(c.get("timestamp", ""))
            if secs is None:
                violations.append(Violation("chapters", f"unparseable timestamp: {c.get('timestamp')}"))
                continue
            if prev is not None and secs - prev < MIN_CHAPTER_GAP_SECONDS:
                violations.append(Violation("chapters", f"timestamps too close together near {c.get('timestamp')}"))
            prev = secs

    return violations


def repair_output(api_keys: list[str], data: dict, violations: list[Violation]) -> dict:
    """One follow-up call asking the model to fix only what's wrong. Makes a network call."""
    issues = "; ".join(f"{v.field}: {v.reason}" for v in violations)
    repair_prompt = (
        "Your previous JSON response had these problems:\n"
        f"{issues}\n\n"
        "Return a corrected JSON object with the same schema, fixing only these "
        "issues. Keep everything else the same.\n\n"
        f"Previous response:\n{json.dumps(data)}"
    )
    response = generate_content_with_fallback(
        api_keys,
        model=MODEL,
        contents=repair_prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=SEO_SCHEMA,
            temperature=0.4,
        ),
    )
    return json.loads(response.text)


def generate_seo(
    api_keys: list[str],
    title: str,
    description: str,
    existing_tags: list[str],
    transcript: str | None,
) -> dict:
    user_prompt = _build_user_prompt(title, description, existing_tags, transcript)

    response = generate_content_with_fallback(
        api_keys,
        model=MODEL,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=SEO_SCHEMA,
            temperature=0.4,
        ),
    )

    try:
        data = json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model did not return valid JSON: {exc}\nRaw: {response.text[:500]}") from exc

    for key, default in (
        ("tags", []), ("chapters", []), ("suggestions", []),
        ("titles", []), ("description", ""), ("hashtags", []),
        ("hook_analysis", {"verdict": "", "reasoning": "", "rewrite": ""}),
    ):
        data.setdefault(key, default)

    violations = find_output_violations(data, has_transcript=bool(transcript))
    if violations:
        try:
            data = repair_output(api_keys, data, violations)
        except Exception:
            pass  # repair is best-effort; keep the original data if it fails

    return data
