import difflib
from dataclasses import dataclass


@dataclass
class TagDiff:
    added: list[str]
    removed: list[str]
    kept: list[str]


def diff_tags(existing_tags: list[str], generated_tags: list[str]) -> TagDiff:
    existing_lower = {t.lower(): t for t in existing_tags}
    generated_lower = {t.lower(): t for t in generated_tags}
    return TagDiff(
        added=[generated_lower[k] for k in generated_lower if k not in existing_lower],
        removed=[existing_lower[k] for k in existing_lower if k not in generated_lower],
        kept=[generated_lower[k] for k in generated_lower if k in existing_lower],
    )


def diff_description(existing_description: str, generated_description: str) -> list[str]:
    """Line-level unified diff, '+'/'-' prefixed, for a before/after view."""
    existing_lines = existing_description.splitlines()
    generated_lines = generated_description.splitlines()
    return list(
        difflib.unified_diff(existing_lines, generated_lines, lineterm="", n=0)
    )
