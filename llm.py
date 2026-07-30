import json
import re

from groq import Groq

MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = (
    "You are an SEO assistant for YouTube creators. Given a video's title, "
    "description, existing tags, and transcript (if available), respond with "
    "ONLY a JSON object, no markdown fences, no commentary, in this exact shape:\n"
    "{\n"
    '  "tags": ["...", "..."],\n'
    '  "chapters": [{"timestamp": "00:00", "title": "..."}],\n'
    '  "suggestions": ["...", "..."]\n'
    "}\n"
    "Rules:\n"
    "- tags: at least 35 relevant, specific SEO keywords/phrases for this exact video.\n"
    "- chapters: only include if a transcript was provided; first chapter must be "
    '"00:00"; timestamps strictly increasing; base them on real topic shifts in '
    "the transcript. If no transcript was provided, return an empty list.\n"
    "- suggestions: actionable, specific ideas to improve this video's reach and "
    "content, not generic advice."
)


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


def _extract_json(raw: str) -> dict:
    raw = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1)
    return json.loads(raw)


def generate_seo(
    api_key: str,
    title: str,
    description: str,
    existing_tags: list[str],
    transcript: str | None,
) -> dict:
    client = Groq(api_key=api_key)
    user_prompt = _build_user_prompt(title, description, existing_tags, transcript)

    completion = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.4,
    )
    raw = completion.choices[0].message.content

    try:
        data = _extract_json(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM did not return valid JSON: {exc}\nRaw: {raw[:500]}") from exc

    data.setdefault("tags", [])
    data.setdefault("chapters", [])
    data.setdefault("suggestions", [])
    return data
