from dataclasses import dataclass

TITLE_MAX = 100
DESCRIPTION_MAX = 5000
TAGS_MAX = 500
HASHTAGS_MAX = 15


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
