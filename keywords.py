import re
from collections import Counter
from dataclasses import dataclass

# Combining marks (Unicode categories Mn/Mc/Me) for the scripts this app
# realistically sees, generated from unicodedata over the combining-diacritic,
# Cyrillic/Hebrew/Arabic and Indic/Thai blocks. Regenerating this is a test
# (test_keywords.py::test_mark_ranges_cover_every_indic_mark), not a manual job.
#
# These are listed explicitly because Python's `\w` does NOT match them --
# they are marks, not alphanumerics. That distinction is the whole bug this
# constant exists to fix: `\w+` does not merely drop Indic text, it SHATTERS
# it into plausible-looking fake words ("जर्मनी" -> ["जर", "मन"]), which is
# strictly worse than dropping it, because the fragments survive as candidate
# keywords and nothing downstream can tell they are debris.
_COMBINING_MARKS = (
    "\u0300-\u036f\u0483-\u0489\u0591-\u05bd\u05bf"
    "\u05c1-\u05c2\u05c4-\u05c5\u05c7\u0610-\u061a"
    "\u064b-\u065f\u0670\u06d6-\u06dc\u06df-\u06e4"
    "\u06e7-\u06e8\u06ea-\u06ed\u0900-\u0903\u093a-\u093c"
    "\u093e-\u094f\u0951-\u0957\u0962-\u0963\u0981-\u0983"
    "\u09bc\u09be-\u09c4\u09c7-\u09c8\u09cb-\u09cd"
    "\u09d7\u09e2-\u09e3\u09fe\u0a01-\u0a03"
    "\u0a3c\u0a3e-\u0a42\u0a47-\u0a48\u0a4b-\u0a4d"
    "\u0a51\u0a70-\u0a71\u0a75\u0a81-\u0a83"
    "\u0abc\u0abe-\u0ac5\u0ac7-\u0ac9\u0acb-\u0acd"
    "\u0ae2-\u0ae3\u0afa-\u0aff\u0b01-\u0b03\u0b3c"
    "\u0b3e-\u0b44\u0b47-\u0b48\u0b4b-\u0b4d\u0b55-\u0b57"
    "\u0b62-\u0b63\u0b82\u0bbe-\u0bc2\u0bc6-\u0bc8"
    "\u0bca-\u0bcd\u0bd7\u0c00-\u0c04\u0c3c"
    "\u0c3e-\u0c44\u0c46-\u0c48\u0c4a-\u0c4d\u0c55-\u0c56"
    "\u0c62-\u0c63\u0c81-\u0c83\u0cbc\u0cbe-\u0cc4"
    "\u0cc6-\u0cc8\u0cca-\u0ccd\u0cd5-\u0cd6\u0ce2-\u0ce3"
    "\u0cf3\u0d00-\u0d03\u0d3b-\u0d3c\u0d3e-\u0d44"
    "\u0d46-\u0d48\u0d4a-\u0d4d\u0d57\u0d62-\u0d63"
    "\u0d81-\u0d83\u0dca\u0dcf-\u0dd4\u0dd6"
    "\u0dd8-\u0ddf\u0df2-\u0df3\u0e31\u0e34-\u0e3a"
    "\u0e47-\u0e4e"
)

# A word is one alphanumeric character (any script -- `[^\W_]` is Unicode-aware
# and excludes the underscore `\w` would otherwise allow) followed by any mix
# of further alphanumerics, combining marks, and internal apostrophes.
#
# Written as an alternation rather than one negated class on purpose: `[^\W_...]`
# negates EVERYTHING inside it, so folding the marks in there would exclude the
# very characters this is meant to keep -- which is exactly the bug the first
# attempt at this fix shipped.
#
# Known limitation, deliberately not papered over: scripts that do not delimit
# words with spaces (Chinese, Japanese, Thai) tokenize as one run per span.
# Correct segmentation needs a dictionary-based segmenter, which is a real
# dependency this module has consistently declined to take on. Those languages
# degrade the same way they did before; they simply no longer corrupt the
# Latin/Indic path around them.
_ALNUM = r"[^\W_]"
_WORD_PATTERN = re.compile(_ALNUM + r"(?:" + _ALNUM + r"|[" + _COMBINING_MARKS + r"'\u2019])*")

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

# Hindi function words, in both scripts they actually appear in.
#
# Needed in two different ways. The Devanagari half only became reachable
# once tokenization stopped discarding non-Latin text -- without it, fixing
# the tokenizer would have made output WORSE, surfacing "के लिए" and "है कि"
# as this video's top keywords. The romanized half fixes a bug that has been
# live all along: Indian creators routinely write Hinglish in Latin script,
# and "ke liye" already outranks real keywords on such videos today, because
# an English-only stopword list has no idea what it is looking at.
#
# Words that are also ordinary English ("main", "ab", "us") are deliberately
# LEFT OUT: dropping a genuine English keyword to catch a Hindi function word
# is the wrong trade, and those three carry real meaning in English titles.
_HINDI_STOPWORDS = {
    # Devanagari
    "का", "के", "की", "को", "है", "हैं", "हो", "होता", "होती", "था", "थे",
    "थी", "में", "से", "पर", "और", "या", "भी", "नहीं", "यह", "वह", "ये",
    "वे", "इस", "उस", "एक", "कि", "जो", "तो", "ही", "कर", "करने", "किया",
    "गया", "गई", "लिए", "साथ", "बहुत", "कुछ", "सब", "अपने", "हम", "आप",
    "क्या", "कैसे", "कहाँ", "कब", "क्यों", "जब", "तक", "बाद", "पहले",
    # Romanized (Hinglish)
    "ka", "ke", "ki", "ko", "hai", "hain", "ho", "hota", "hoti", "tha",
    "thi", "mein", "par", "aur", "ya", "bhi", "nahi", "nahin", "yeh",
    "woh", "kya", "kaise", "kahan", "kab", "kyun", "kyu", "jab", "tak",
    "baad", "pehle", "karne", "kiya", "gaya", "gayi", "liye", "saath",
    "bahut", "kuch", "sab", "apne", "hum", "aap", "toh", "bas",
}

_STOPWORDS |= _HINDI_STOPWORDS

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


# Minimum length of a stem. Below this, suffix stripping destroys the word
# rather than normalizing it -- "aps" would become "ap", and acronyms are the
# single highest-value seed class this app has (see keyword_pipeline's entity
# detector), so mangling them is the one outcome worth guarding hardest.
_MIN_STEM_CHARS = 3

# Suffixes are checked longest-first: "universities" has to be caught by the
# -ies rule before the bare -s rule reaches it.
_SUFFIX_RULES = [
    ("sses", "ss"),   # classes -> class
    ("ies", "y"),     # universities -> university
    ("ing", ""),      # studying -> study
    ("ed", ""),       # applied -> appli
    ("s", ""),        # certificates -> certificate
]

# "-es" is only a plural marker after a sibilant (boxes, dishes, churches).
# Everywhere else the plural is a bare "-s" and the "e" belongs to the stem,
# so treating "-es" as a suffix unconditionally splits the very pair this
# function exists to join: "certificates" would stem to "certificat" while
# "certificate" stems to itself, and they would stop matching.
_ES_AFTER = ("x", "z", "ch", "sh", "s")

# Words whose ending merely looks like a suffix. Stripping these produces a
# different word ("news" -> "new") rather than a normalized one.
_NO_STEM = {"news", "gas", "bus", "plus", "this", "always", "less", "class"}


def stem(word: str) -> str:
    """Crude English suffix normalizer, NOT a linguistic stemmer.

    Exists for one job: make "certificate"/"certificates" and
    "university"/"universities" compare equal when scoring relevance and
    coverage. Without it a plural variant of the right keyword scores below
    RELEVANCE_FLOOR and is dropped, while the singular survives -- the same
    keyword, deleted for its grammatical number.

    Hand-rolled rather than pulling in snowballstemmer for the same reason
    candidates.py hand-rolls TF-IDF: this file's whole text stack is
    dependency-free by policy, and the cases that actually matter here are
    plurals and gerunds, not the full Porter rule set.

    Non-Latin scripts are returned untouched: Devanagari and Tamil do not
    form plurals by suffixing an English letter, so every rule below is a
    no-op at best and corruption at worst.
    """
    if word in _NO_STEM or not word.isascii() or not word.isalpha():
        return word
    if word.endswith("ss"):
        return word  # process, address -- the -s rules must not touch these
    if word.endswith("es") and word[:-2].endswith(_ES_AFTER):
        stemmed = word[:-2]
        return stemmed if len(stemmed) >= _MIN_STEM_CHARS else word
    for suffix, replacement in _SUFFIX_RULES:
        if word.endswith(suffix):
            stemmed = word[: -len(suffix)] + replacement
            if len(stemmed) >= _MIN_STEM_CHARS:
                return stemmed
            return word  # too short to be a real stem -- keep the original
    return word


def stem_words(text: str) -> list[str]:
    """Stemmed tokens, for MATCHING only.

    Deliberately separate from _clean_words, which keeps surface forms.
    Anything a user reads -- n-grams, candidate phrases, the keywords in the
    final report -- has to stay in its original spelling; stemming there
    would put "aps certificat" on screen as a recommended tag. Only the
    scoring paths (relevance cosine, coverage overlap) consume this.
    """
    return [stem(w) for w in _clean_words(text)]


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
