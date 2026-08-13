"""Whether a planning-mode draft has enough typed input to work from.

Lives in its own module rather than app.py so it can be unit-tested --
importing app.py executes the whole Streamlit script.
"""

import re

PLAN_MIN_TITLE_WORDS = 4

# Words that add no topical information to a title. A title made only of
# these ("my new video about this") clears any naive word-count check while
# telling the pipeline nothing at all.
_FILLER_WORDS = {
    "a", "an", "the", "my", "new", "video", "about", "on", "for", "to", "of",
    "and", "or", "in", "with", "this", "that", "is", "how", "why", "what",
}

_WORD_PATTERN = re.compile(r"[A-Za-z0-9']+")


def is_plan_input_sufficient(
    title: str, description: str, script: str, tags: list[str],
) -> bool:
    """Deliberately a hard gate, not a degradation path.

    Everything downstream in planning mode -- autocomplete seeds, target
    audience, keyword demand -- is derived purely from what the user typed.
    Unlike the analyze path, there is no real video metadata to fall back on.
    Too little input therefore does not produce a slightly worse plan; it
    produces a confident plan about nothing, which is worse than refusing.

    Sufficient means: a title carrying at least PLAN_MIN_TITLE_WORDS
    non-filler words (so "MBA in Germany for Indian students" passes and
    "my new video" does not), OR any real description/script/tags.
    """
    if description.strip() or script.strip() or tags:
        return True
    meaningful = [
        word for word in _WORD_PATTERN.findall(title.lower())
        if word not in _FILLER_WORDS
    ]
    return len(meaningful) >= PLAN_MIN_TITLE_WORDS
