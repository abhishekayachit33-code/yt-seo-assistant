"""Filler-word and sentence-length scan on a script or transcript.

A general script-quality signal, not specific to planning mode -- it reads
the same whether the text came from a pasted draft or a real video's
transcript. Pure regex, no NLP dependency, matching the rest of the
codebase's text-analysis modules (keywords.py, shelf_life.py).
"""

import re
from dataclasses import dataclass, field

FILLER_WORDS = [
    "um", "uh", "like", "so", "you know", "basically", "actually",
    "literally", "kind of", "sort of",
]

_SENTENCE_SPLIT_PATTERN = re.compile(r"[.!?]+")
_WORD_TOKEN_PATTERN = re.compile(r"\S+")
_TIMESTAMP_PATTERN = re.compile(r"\[\d{2}:\d{2}\]")

_FILLER_PATTERNS = [
    (word, re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE))
    for word in FILLER_WORDS
]


@dataclass
class FillerHit:
    word: str
    count: int


@dataclass
class ReadabilityReport:
    filler_hits: list[FillerHit] = field(default_factory=list)
    total_filler_count: int = 0
    word_count: int = 0
    sentence_count: int = 0
    avg_sentence_length: float = 0.0

    @property
    def filler_rate(self) -> float:
        """Fillers per 100 words -- comparable regardless of script length."""
        return round(self.total_filler_count / self.word_count * 100, 1) if self.word_count else 0.0


def scan_readability(script: str | None) -> ReadabilityReport | None:
    """None for empty/whitespace-only script, since there's nothing to scan."""
    if not script or not script.strip():
        return None

    # Live-transcript text carries "[mm:ss] " prefixes per line -- strip them
    # so they don't get counted as words or split sentences oddly.
    text = _TIMESTAMP_PATTERN.sub("", script)

    word_count = len(_WORD_TOKEN_PATTERN.findall(text))
    if word_count == 0:
        return None

    hits = []
    total = 0
    for word, pattern in _FILLER_PATTERNS:
        count = len(pattern.findall(text))
        if count:
            hits.append(FillerHit(word=word, count=count))
            total += count

    sentences = [s for s in _SENTENCE_SPLIT_PATTERN.split(text) if s.strip()]
    sentence_count = len(sentences)
    avg_sentence_length = round(word_count / sentence_count, 1) if sentence_count else 0.0

    return ReadabilityReport(
        filler_hits=sorted(hits, key=lambda h: -h.count),
        total_filler_count=total,
        word_count=word_count,
        sentence_count=sentence_count,
        avg_sentence_length=avg_sentence_length,
    )
