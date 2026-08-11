import json
from dataclasses import dataclass

from google.genai import types

from gemini_client import generate_content_with_fallback
from limits import TAGS_MAX

MODEL = "gemini-flash-latest"

SYSTEM_PROMPT = """
    You are a senior, data-driven YouTube Growth Strategist. Your job is to analyze a video's existing metadata (title, description, tags), transcript, and audience comments, and prescribe highly specific, evidence-based optimizations.

CRITICAL RULE: Act as a diagnostic consultant. Do not change things just to change them. If the original metadata is already highly optimized, acknowledge its strengths. Every recommendation MUST be justified by data from the transcript or comments.

Output Constraints:
- titles: Provide 5 optimized titles (under 100 characters). If the original title is weak, explain why in the 'rationale' field. Focus on curiosity, search intent, and emotional hooks.
- tags: Provide exactly 35 high-value SEO keywords/phrases. Do not use generic tags. Extract specific n-grams and entities directly from the transcript.
- description: Write a fully optimized description. It must include an engaging hook, fold in the chapter timestamps (if transcript is provided), and end with a clear CTA. 
- chapters: First chapter MUST be "00:00". Timestamps must be strictly increasing, >10 seconds apart, and tied to ACTUAL topic shifts in the transcript. If no transcript, return empty.
- suggestions: Provide 3 strategic, actionable recommendations to improve retention or reach. (e.g., "At 02:15, you dropped the pacing. Next time, use a B-roll cut here.") NO generic advice.
- hook_analysis: Diagnose the first 30 seconds of the transcript. Assign a verdict (Strong/Weak). If weak, provide a specific rewrite to improve viewer retention.
- comment_sentiment: Analyze the provided comments. Pinpoint specific themes, complaints, or praises. Quote actual themes. If the audience is asking for a specific follow-up, flag it.
- shorts_scripts: Extract 3 highly engaging moments from the transcript to repurpose as vertical video (<60 seconds). Include a 3-second visual hook instruction, the spoken script, and a social caption.
- social_posts: Draft promotional copy optimized for platform algorithms: a Twitter/X thread (3-5 tweets), a professional LinkedIn post, and an engaging YouTube Community poll/post.

For every single generation (titles, tags, scripts), you MUST include a brief 'rationale' explaining exactly why this change will increase CTR, search ranking, or retention based on the provided context.
"""

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
        "comment_sentiment": {
            "type": "object",
            "properties": {
                "positive_themes": {"type": "array", "items": {"type": "string"}},
                "negative_themes": {"type": "array", "items": {"type": "string"}},
                "summary": {"type": "string"},
            },
            "required": ["positive_themes", "negative_themes", "summary"],
        },
        "shorts_scripts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "hook_line": {"type": "string"},
                    "script": {"type": "string"},
                    "caption": {"type": "string"},
                },
                "required": ["hook_line", "script", "caption"],
            },
        },
        "social_posts": {
            "type": "object",
            "properties": {
                "twitter_thread": {"type": "string"},
                "linkedin_post": {"type": "string"},
                "community_post": {"type": "string"},
            },
            "required": ["twitter_thread", "linkedin_post", "community_post"],
        },
    },
    "required": [
        "tags", "chapters", "suggestions", "titles",
        "description", "hashtags", "hook_analysis", "comment_sentiment",
        "shorts_scripts", "social_posts",
    ],
}

MIN_TAGS = 35
MIN_CHAPTER_GAP_SECONDS = 10


@dataclass
class Violation:
    field: str
    reason: str


def _build_user_prompt(
    title: str,
    description: str,
    existing_tags: list[str],
    transcript: str | None,
    comments: list[str] | None = None,
) -> str:
    parts = [
        f"Title: {title}",
        f"Existing tags: {', '.join(existing_tags) if existing_tags else '(none)'}",
        f"Description:\n{description[:2000]}",
    ]
    if transcript:
        parts.append(f"Transcript:\n{transcript}")
    else:
        parts.append("Transcript: (not available for this video)")
    if comments:
        numbered = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(comments))
        parts.append(f"Viewer comments:\n{numbered}")
    else:
        parts.append("Viewer comments: (none available for this video)")
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
    tags_chars = len(", ".join(tags))
    if tags_chars > TAGS_MAX:
        violations.append(
            Violation("tags", f"combined tag length is {tags_chars} characters, YouTube's limit is {TAGS_MAX}")
        )

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


def enforce_tag_char_limit(tags: list[str], max_chars: int = TAGS_MAX) -> list[str]:
    """Deterministic backstop, not best-effort: repair_output asks the model to
    fix an oversized tag list, but nothing guarantees it complies (it didn't,
    once, in production -- 991 characters against a 500 limit). Greedily keeps
    tags in order until the ", "-joined length would exceed max_chars, even if
    that drops the count below MIN_TAGS. YouTube's real cap is authoritative;
    this app's own 35-tag minimum is a heuristic and must lose that conflict."""
    kept: list[str] = []
    length = 0
    for tag in tags:
        added = len(tag) + (2 if kept else 0)  # ", " separator before all but the first
        if length + added > max_chars:
            break
        kept.append(tag)
        length += added
    return kept


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


_PLANNING_CHAPTER_OVERRIDE = (
    "\nThis video has not been recorded or uploaded yet -- always return an "
    "empty chapters list regardless of whether transcript text was provided, "
    "since there is no real duration to base timestamps on."
)


def generate_seo(
    api_keys: list[str],
    title: str,
    description: str,
    existing_tags: list[str],
    transcript: str | None,
    comments: list[str] | None = None,
    suppress_chapters: bool = False,
) -> dict:
    user_prompt = _build_user_prompt(title, description, existing_tags, transcript, comments)
    system_prompt = SYSTEM_PROMPT + _PLANNING_CHAPTER_OVERRIDE if suppress_chapters else SYSTEM_PROMPT

    response = generate_content_with_fallback(
        api_keys,
        model=MODEL,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
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
        ("comment_sentiment", {"positive_themes": [], "negative_themes": [], "summary": ""}),
        ("shorts_scripts", []),
        ("social_posts", {"twitter_thread": "", "linkedin_post": "", "community_post": ""}),
    ):
        data.setdefault(key, default)

    if suppress_chapters:
        # Cleared before violation-checking too, not just at the end: an empty
        # chapters list can't trip find_output_violations' chapter rules, so
        # this avoids a wasted repair round-trip over something about to be
        # discarded anyway.
        data["chapters"] = []

    violations = find_output_violations(data, has_transcript=bool(transcript))
    if violations:
        try:
            data = repair_output(api_keys, data, violations)
            data.setdefault("tags", [])
        except Exception:
            pass  # repair is best-effort; keep the original data if it fails

    # Unconditional, not just on a detected violation: guarantees the shipped
    # tags never exceed YouTube's real 500-character cap regardless of what
    # the model (or its repair attempt) actually returned.
    data["tags"] = enforce_tag_char_limit(data.get("tags", []))

    if suppress_chapters:
        # Same belt-and-suspenders pattern as the tag limit above: the prompt
        # override asks the model to omit chapters, but repair_output() runs
        # against the base SYSTEM_PROMPT and could reintroduce them, so this
        # is enforced unconditionally rather than trusted to the model.
        data["chapters"] = []

    return data
