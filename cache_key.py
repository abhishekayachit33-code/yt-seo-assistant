"""Identifies whether two Analyze runs would produce the same Gemini output,
so a cached result can be shared across every user instead of just the one
who first analyzed a given video -- the analysis is a property of the video's
public metadata plus the prompt version, not of who clicked Analyze.
"""

import hashlib

from llm import PROMPT_VERSION


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_fingerprint(
    title: str,
    description: str,
    tags: list[str],
    transcript: str | None,
    comments: list[str] | None,
) -> str:
    """Two calls only produce the same fingerprint if every one of these
    matches, including PROMPT_VERSION -- tags are sorted since their order
    doesn't affect the prompt's meaning, but nothing else is normalized,
    since even a title/description edit on YouTube should force a fresh
    analysis rather than silently serving a stale cached one."""
    parts = [
        f"v={PROMPT_VERSION}",
        f"title={title}",
        f"description={description}",
        f"tags={','.join(sorted(tags or []))}",
        f"transcript={_hash(transcript) if transcript else 'none'}",
        f"comments={_hash(chr(31).join(comments)) if comments else 'none'}",
    ]
    return _hash("\n".join(parts))
