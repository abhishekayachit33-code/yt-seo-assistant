import re
from dataclasses import dataclass

# Real YouTube-enforced limits. Exceeding these breaks the upload or, for
# hashtags specifically, makes YouTube silently discard ALL of them -- not
# just the excess.
TITLE_MAX = 100
DESCRIPTION_MAX = 5000
TAGS_MAX = 500
HASHTAGS_MAX = 15

# This app's own recommendations, not YouTube rules. Distinguished from the
# hard limits above on purpose -- compute_health_score below scores against
# both, and conflating the two means a user can't tell "you'll break your
# upload" from "we think this is good practice."
DESCRIPTION_MIN_RECOMMENDED = 200
MIN_TAG_COUNT_RECOMMENDED = 35
# 3-5 is the actual current best practice: YouTube only ever displays the
# first 3 hashtags (above the title), and creators who stuff more than a
# handful risk being read as spam. The old value here (10) rewarded hashtag
# stuffing, scored against best practice rather than for it, and nothing in
# llm.py's prompt even aimed for that count in the first place -- checked
# and corrected together.
HASHTAGS_MIN_RECOMMENDED = 3
HASHTAGS_MAX_RECOMMENDED = 5

_SOCIAL_LINK_PATTERN = re.compile(
    r"(https?://\S+|@\w+|(?:instagram|twitter|x|tiktok|discord|facebook)\.com/\S+)",
    re.IGNORECASE,
)

_HASHTAG_PATTERN = re.compile(r"#\w+")


def extract_hashtags(text: str) -> list[str]:
    """A published video has no separate hashtag field -- its hashtags live in
    the description. Pulling them out lets the original metadata be scored on
    the same footing as the generated metadata."""
    return _HASHTAG_PATTERN.findall(text or "")


@dataclass
class LimitCheck:
    label: str
    current: int
    maximum: int

    @property
    def ok(self) -> bool:
        return self.current <= self.maximum


def check_limits(title: str, description: str, tags: list[str], hashtags: list[str]) -> list[LimitCheck]:
    tags_chars = len(", ".join(tags))
    return [
        LimitCheck("Title", len(title), TITLE_MAX),
        LimitCheck("Description", len(description), DESCRIPTION_MAX),
        LimitCheck("Tags (combined characters)", tags_chars, TAGS_MAX),
        LimitCheck("Hashtags (count)", len(hashtags), HASHTAGS_MAX),
    ]


@dataclass
class HealthRule:
    label: str
    passed: bool
    detail: str


def compute_health_score(title: str, description: str, tags: list[str], hashtags: list[str]) -> tuple[int, list[HealthRule]]:
    """0-100 score across 7 rules. Not all 7 are the same kind of claim:
    title/description/tag-char limits are real YouTube constraints (using
    TITLE_MAX/DESCRIPTION_MAX/TAGS_MAX); tag COUNT and hashtag range are this
    app's own heuristics (MIN_TAG_COUNT_RECOMMENDED, HASHTAGS_MIN/MAX_
    RECOMMENDED) with no YouTube rule behind them. Scored on equal footing
    here for a single 0-100 number, but don't read every rule as "YouTube
    says so" -- two of them are this app's opinion."""
    rules = [
        HealthRule(
            "Title within 100 characters",
            len(title) <= TITLE_MAX,
            f"{len(title)}/{TITLE_MAX} characters",
        ),
        HealthRule(
            "Description is substantial (200+ characters)",
            len(description) >= DESCRIPTION_MIN_RECOMMENDED,
            f"{len(description)} characters",
        ),
        HealthRule(
            "Description within 5000 characters",
            len(description) <= DESCRIPTION_MAX,
            f"{len(description)}/{DESCRIPTION_MAX} characters",
        ),
        HealthRule(
            f"At least {MIN_TAG_COUNT_RECOMMENDED} tags",
            len(tags) >= MIN_TAG_COUNT_RECOMMENDED,
            f"{len(tags)} tags",
        ),
        HealthRule(
            "Tags within 500 combined characters",
            len(", ".join(tags)) <= TAGS_MAX,
            f"{len(', '.join(tags))}/{TAGS_MAX} characters",
        ),
        HealthRule(
            f"{HASHTAGS_MIN_RECOMMENDED}-{HASHTAGS_MAX_RECOMMENDED} hashtags",
            HASHTAGS_MIN_RECOMMENDED <= len(hashtags) <= HASHTAGS_MAX_RECOMMENDED,
            f"{len(hashtags)} hashtags",
        ),
        HealthRule(
            "Description links to a social/community profile",
            bool(_SOCIAL_LINK_PATTERN.search(description)),
            "link or handle found" if _SOCIAL_LINK_PATTERN.search(description) else "no link or handle found",
        ),
    ]
    score = round(100 * sum(r.passed for r in rules) / len(rules))
    return score, rules
