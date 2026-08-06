"""Evergreen vs. trending classification.

A pure rule engine: it counts language that dates a video (years, months,
"breaking", "update") against language that keeps it searchable for years
("how to", "tutorial", "explained"), weighting each signal by where it appears.
A phrase in the title says far more about shelf life than the same phrase
buried in the transcript, so the title carries the most weight.
"""

import re
from dataclasses import dataclass, field

# Where a signal appears determines how much it counts.
TITLE_WEIGHT = 3
TAG_WEIGHT = 2
TRANSCRIPT_WEIGHT = 1

TRENDING_PATTERNS = [
    r"\b20\d{2}\b",
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b",
    r"\b(news|latest|update|updated|breaking|today|tonight|this week|this month)\b",
    r"\b(just (?:released|announced|dropped)|new release|announcement|leak|leaked)\b",
    r"\b(reaction|recap|live|q[1-4]|earnings)\b",
]

EVERGREEN_PATTERNS = [
    r"\b(how to|how i|guide|tutorial|walkthrough)\b",
    r"\b(beginner|beginners|basics|fundamentals|introduction|intro to|101)\b",
    r"\b(explained|explainer|what is|why does|understanding)\b",
    r"\b(step by step|complete course|masterclass|deep dive|from scratch)\b",
    r"\b(tips|best practices|common mistakes|cheat sheet)\b",
]

_TRENDING = [re.compile(p, re.IGNORECASE) for p in TRENDING_PATTERNS]
_EVERGREEN = [re.compile(p, re.IGNORECASE) for p in EVERGREEN_PATTERNS]


@dataclass
class ShelfLife:
    evergreen_score: int  # 0-100; 100 is purely evergreen
    classification: str
    expectation: str
    evergreen_hits: list[str] = field(default_factory=list)
    trending_hits: list[str] = field(default_factory=list)

    @property
    def is_unclassified(self) -> bool:
        return not self.evergreen_hits and not self.trending_hits


def _hits(patterns: list[re.Pattern], text: str) -> list[str]:
    found = []
    for pattern in patterns:
        for match in pattern.findall(text or ""):
            # findall returns tuples when a pattern has groups.
            found.append(match if isinstance(match, str) else next((m for m in match if m), ""))
    return [f.lower() for f in found if f]


def classify(title: str, tags: list[str], transcript: str | None) -> ShelfLife:
    tag_text = " ".join(tags or [])
    sources = [
        (title or "", TITLE_WEIGHT),
        (tag_text, TAG_WEIGHT),
        (transcript or "", TRANSCRIPT_WEIGHT),
    ]

    evergreen_weight = trending_weight = 0
    evergreen_hits: list[str] = []
    trending_hits: list[str] = []

    for text, weight in sources:
        found_evergreen = _hits(_EVERGREEN, text)
        found_trending = _hits(_TRENDING, text)
        evergreen_weight += len(found_evergreen) * weight
        trending_weight += len(found_trending) * weight
        evergreen_hits += found_evergreen
        trending_hits += found_trending

    total = evergreen_weight + trending_weight
    # Nothing matched either way: stay neutral rather than inventing a verdict.
    score = 50 if total == 0 else round(evergreen_weight / total * 100)

    if total == 0:
        classification, expectation = (
            "Unclassified",
            "No strong dating or how-to language either way — shelf life will follow the topic itself.",
        )
    elif score >= 75:
        classification, expectation = (
            "Evergreen",
            "Expect a slow initial spike but steady search traffic for 24+ months.",
        )
    elif score >= 55:
        classification, expectation = (
            "Mostly evergreen",
            "Expect a modest launch and useful search traffic for 6 to 24 months.",
        )
    elif score > 45:
        classification, expectation = (
            "Mixed",
            "Part reference, part moment — a launch spike, then a few months of tail.",
        )
    elif score >= 25:
        classification, expectation = (
            "Mostly trending",
            "Expect most views in the first weeks, with little search traffic after a few months.",
        )
    else:
        classification, expectation = (
            "Trending",
            "Expect a sharp spike and a short tail — most views land within days.",
        )

    return ShelfLife(
        evergreen_score=score,
        classification=classification,
        expectation=expectation,
        evergreen_hits=sorted(set(evergreen_hits)),
        trending_hits=sorted(set(trending_hits)),
    )
