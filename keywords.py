import re
from collections import Counter
from dataclasses import dataclass

_WORD_PATTERN = re.compile(r"[a-z0-9']+")

_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "so", "to", "of", "in", "on",
    "at", "by", "for", "with", "about", "as", "is", "it", "its", "this",
    "that", "these", "those", "i", "you", "he", "she", "we", "they", "them",
    "my", "your", "our", "their", "be", "was", "were", "are", "am", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "can", "could", "shall", "should", "may", "might", "must", "not", "no",
    "yes", "just", "like", "get", "got", "go", "going", "one", "up", "out",
    "there", "here", "what", "when", "where", "how", "all", "some", "into",
}

# MULTILINE so `^` matches the start of every line, not just the start of
# the whole string -- a real transcript is many "[MM:SS] text" lines joined
# with "\n" (see transcript.segments_to_text), and without this flag only
# the very first timestamp gets stripped. Every later line's "[08:01]" etc.
# was surviving into the word stream as two "words" ("08", "01"), which then
# slid straight into the bigram/trigram window as if they were real phrases.
_TIMESTAMP_PATTERN = re.compile(r"^\[\d{2}:\d{2}\]\s*", re.MULTILINE)


def _clean_words(text: str) -> list[str]:
    text = _TIMESTAMP_PATTERN.sub("", text)
    return [w for w in _WORD_PATTERN.findall(text.lower()) if w not in _STOPWORDS and len(w) > 1]


def top_ngrams(text: str, n: int, top_k: int = 15) -> list[tuple[str, int]]:
    """Top n-word phrases by frequency, stripped of timestamps and stopwords.
    n=1 is single keywords, n=2/3 are the more useful SEO-relevant phrases."""
    words = _clean_words(text)
    if len(words) < n:
        return []
    phrases = [" ".join(words[i:i + n]) for i in range(len(words) - n + 1)]
    return Counter(phrases).most_common(top_k)


DEFAULT_WORDS_PER_MINUTE = 140
_SPEED_BAND = 0.15  # +/-15%, wide enough that this reads as an estimate, not a measurement

_WORD_TOKEN_PATTERN = re.compile(r"\S+")


@dataclass
class SpeechEstimate:
    word_count: int
    low_minutes: float
    high_minutes: float

    @property
    def label(self) -> str:
        low, high = round(self.low_minutes), round(self.high_minutes)
        if low == high:
            return f"~{self.word_count:,} words — roughly {low} minute{'s' if low != 1 else ''} at a typical speaking pace"
        return f"~{self.word_count:,} words — roughly {low}-{high} minutes at a typical speaking pace"


def estimate_spoken_length(script: str | None, wpm: int = DEFAULT_WORDS_PER_MINUTE) -> SpeechEstimate | None:
    """A deliberately wide estimate, never a single precise-looking number --
    this must not read like pacing.py's real measured words-per-minute chart,
    which only exists for a video with an actual transcript and timing.
    None for empty/whitespace-only script, since there's nothing to estimate."""
    if not script or not script.strip():
        return None
    word_count = len(_WORD_TOKEN_PATTERN.findall(script))
    if word_count == 0:
        return None
    return SpeechEstimate(
        word_count=word_count,
        low_minutes=word_count / (wpm * (1 + _SPEED_BAND)),
        high_minutes=word_count / (wpm * (1 - _SPEED_BAND)),
    )
