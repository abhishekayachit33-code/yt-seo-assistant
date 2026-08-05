import re
from dataclasses import dataclass

TITLE_MAX = 100
DESCRIPTION_MAX = 5000
TAGS_MAX = 500
HASHTAGS_MAX = 15

DESCRIPTION_MIN_RECOMMENDED = 200
MIN_TAG_COUNT_RECOMMENDED = 35
HASHTAGS_MIN_RECOMMENDED = 10

_SOCIAL_LINK_PATTERN = re.compile(
    r"(https?://\S+|@\w+|(?:instagram|twitter|x|tiktok|discord|facebook)\.com/\S+)",
    re.IGNORECASE,
)


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
    """0-100 compliance score against YouTube best practices (not just hard
    limits) -- title/description/tag length, tag count, hashtag range, and
    whether the description points viewers to a social/community link."""
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
            f"{HASHTAGS_MIN_RECOMMENDED}-{HASHTAGS_MAX} hashtags",
            HASHTAGS_MIN_RECOMMENDED <= len(hashtags) <= HASHTAGS_MAX,
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
