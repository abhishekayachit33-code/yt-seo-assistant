"""Merges the three evidence lanes into one candidate pool, then cuts it down
cheaply before anything expensive touches it.

The cut is the point of this module. Seed expansion produces several hundred
raw phrases, and handing all of them to an LLM produces mush -- attention
degrades badly across a long list, which is the same failure mode llm.py's
trailing-instruction block exists to fight. Everything here is pure Python
with no I/O, so the expensive stages only ever see survivors.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from keywords import _STOPWORDS, _clean_words, stem_words

# Lanes, kept as explicit provenance rather than a bare string so the final
# output can tell the user WHERE a keyword came from -- "4 competitors use
# this" is evidence, "here is a keyword" is not.
LANE_SUPPLY = "supply"           # what the video itself says
LANE_DEMAND = "demand"           # what people search for
LANE_COMPETITOR = "competitor"   # what already ranks

MIN_PHRASE_CHARS = 3
MAX_PHRASE_CHARS = 60
MAX_PHRASE_WORDS = 8
RELEVANCE_SHORTLIST = 40

# Phrases that are pure filler as a standalone tag. Not a spam blocklist --
# these are words that are perfectly fine INSIDE a longer phrase ("how to get
# a german student visa") but useless alone ("how to").
_JUNK_PHRASES = {
    "how to", "the best", "best", "top", "new", "video", "youtube", "shorts",
    "tips", "guide", "tutorial", "review", "vlog", "explained", "full", "part",
}

_URL_PATTERN = re.compile(r"https?://|www\.|\.com|\.in\b")
_NON_TEXT_PATTERN = re.compile(r"^[\W\d_]+$")


@dataclass
class Candidate:
    phrase: str
    lanes: set[str] = field(default_factory=set)
    autocomplete_rank: int | None = None   # best position seen, None if never suggested
    competitor_hits: int = 0               # how many distinct competitors used it
    relevance: float = 0.0                 # cosine vs the video's own content

    @property
    def word_count(self) -> int:
        return len(self.phrase.split())


def _is_junk(phrase: str) -> bool:
    if len(phrase) < MIN_PHRASE_CHARS or len(phrase) > MAX_PHRASE_CHARS:
        return True
    if len(phrase.split()) > MAX_PHRASE_WORDS:
        return True
    if phrase in _JUNK_PHRASES:
        return True
    if _URL_PATTERN.search(phrase):
        return True
    if _NON_TEXT_PATTERN.match(phrase):
        return True
    # A phrase made entirely of stopwords carries no search intent.
    if all(w in _STOPWORDS for w in phrase.split()):
        return True
    return False


def _normalize(phrase: str) -> str:
    return re.sub(r"\s+", " ", phrase.strip().lower())


def build_pool(
    supply_phrases: list[str] | None = None,
    suggestions: list | None = None,
    competitor_phrases: list[str] | None = None,
) -> list[Candidate]:
    """Merges lanes into one deduplicated pool.

    competitor_phrases is passed with duplicates intact on purpose: the same
    phrase appearing across several competitors is the signal (see
    keyword_rank's consensus gate), so the count is preserved rather than
    collapsed by a set().
    """
    pool: dict[str, Candidate] = {}

    def _get(phrase: str) -> Candidate | None:
        normalized = _normalize(phrase)
        if _is_junk(normalized):
            return None
        if normalized not in pool:
            pool[normalized] = Candidate(phrase=normalized)
        return pool[normalized]

    for phrase in supply_phrases or []:
        candidate = _get(phrase)
        if candidate:
            candidate.lanes.add(LANE_SUPPLY)

    for suggestion in suggestions or []:
        candidate = _get(suggestion.phrase)
        if candidate:
            candidate.lanes.add(LANE_DEMAND)
            if candidate.autocomplete_rank is None or suggestion.rank < candidate.autocomplete_rank:
                candidate.autocomplete_rank = suggestion.rank

    for phrase in competitor_phrases or []:
        candidate = _get(phrase)
        if candidate:
            candidate.lanes.add(LANE_COMPETITOR)
            candidate.competitor_hits += 1

    return deduplicate(list(pool.values()))


# --------------------------------------------------------------- deduplication
#
# The dict above only collapses phrases that are byte-identical after
# whitespace/case normalization, which misses the two ways the same keyword
# actually arrives twice: inflection ("aps certificate germany" vs "aps
# certificates germany") and word order / connecting words ("germany student
# visa" vs "student visa for germany"). Both survive as separate candidates,
# then both consume a slot in a tag list capped at 500 characters -- the
# budget that llm.enforce_tag_char_limit is already fighting over.
#
# Stems make this cheap: two phrases meaning the same thing reduce to the same
# multiset of stems once stopwords are dropped.


def _stem_signature(phrase: str) -> tuple[str, ...]:
    """Order-insensitive identity of a phrase. Sorted rather than a set so a
    genuinely repeated word ("visa visa germany") stays distinct from a single
    mention."""
    return tuple(sorted(stem_words(phrase)))


def _preferred(a: Candidate, b: Candidate) -> tuple[Candidate, Candidate]:
    """(keeper, absorbed). The surviving SURFACE FORM is chosen, deliberately,
    by how people actually type the phrase: a variant Google returned as a
    search suggestion wins over one assembled from a transcript or a
    competitor's title, and a better-ranked suggestion wins over a worse one.
    Everything after that is a deterministic tie-break, because the ranker
    above has a determinism test and this must not become a source of run to
    run drift."""
    a_suggested, b_suggested = a.autocomplete_rank is not None, b.autocomplete_rank is not None
    if a_suggested != b_suggested:
        return (a, b) if a_suggested else (b, a)
    if a_suggested and a.autocomplete_rank != b.autocomplete_rank:
        return (a, b) if a.autocomplete_rank < b.autocomplete_rank else (b, a)
    if len(a.lanes) != len(b.lanes):
        return (a, b) if len(a.lanes) > len(b.lanes) else (b, a)
    if len(a.phrase) != len(b.phrase):
        return (a, b) if len(a.phrase) < len(b.phrase) else (b, a)
    return (a, b) if a.phrase <= b.phrase else (b, a)


def deduplicate(candidates: list[Candidate]) -> list[Candidate]:
    """Collapses phrases that mean the same thing, MERGING their evidence
    rather than discarding the loser's.

    Merging matters most for competitor_hits: two competitors using "germany
    student visa" and one using "student visa germany" is three competitors
    targeting one concept. Kept as separate candidates they read as 2 and 1 --
    the first clears COMPETITOR_CONSENSUS_MIN and the second is discarded as
    noise. Summed, the signal is what it always was.
    """
    groups: dict[tuple, Candidate] = {}
    for candidate in candidates:
        signature = _stem_signature(candidate.phrase)
        if not signature:
            # Nothing comparable left after stopword removal -- leave it
            # alone rather than collapsing every such phrase into one bucket.
            groups[("\x00unique", candidate.phrase)] = candidate
            continue

        existing = groups.get(signature)
        if existing is None:
            groups[signature] = candidate
            continue

        keeper, absorbed = _preferred(existing, candidate)
        keeper.lanes |= absorbed.lanes
        keeper.competitor_hits += absorbed.competitor_hits
        ranks = [
            r for r in (existing.autocomplete_rank, candidate.autocomplete_rank)
            if r is not None
        ]
        keeper.autocomplete_rank = min(ranks) if ranks else None
        groups[signature] = keeper

    return list(groups.values())


# ------------------------------------------------------------------ relevance
#
# TF-IDF cosine, hand-rolled rather than pulled from scikit-learn: the whole
# corpus here is a few hundred short phrases, so a real vectorizer would add a
# heavy dependency to the Docker image for something this file does in ~20
# lines. Swapping this for real embeddings later only changes score_relevance.


def _term_frequencies(text: str) -> Counter:
    # Stemmed, unlike everything user-facing: this Counter is only ever fed
    # to the cosine below, so "certificate" and "certificates" must land in
    # the same bucket. Measured effect on a realistic pool -- a plural
    # variant of an on-topic phrase scored 0.144 against its singular's
    # 0.262, i.e. below RELEVANCE_FLOOR, and was dropped outright for its
    # grammatical number.
    return Counter(stem_words(text))


def _cosine(a: Counter, b: Counter, idf: dict[str, float]) -> float:
    shared = set(a) & set(b)
    if not shared:
        return 0.0
    numerator = sum(a[t] * b[t] * idf.get(t, 0.0) ** 2 for t in shared)
    norm_a = math.sqrt(sum((count * idf.get(t, 0.0)) ** 2 for t, count in a.items()))
    norm_b = math.sqrt(sum((count * idf.get(t, 0.0)) ** 2 for t, count in b.items()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return numerator / (norm_a * norm_b)


def score_relevance(candidates: list[Candidate], reference_text: str) -> None:
    """Scores every candidate against the video's own content, in place.

    reference_text should be the richest description of the video available --
    content_summary plus title plus transcript excerpt. A candidate that
    shares no meaningful vocabulary with it scores 0 and gets cut, which is
    what stops autocomplete's wider sweeps from dragging in off-topic phrases.
    """
    if not reference_text.strip() or not candidates:
        return

    reference = _term_frequencies(reference_text)
    documents = [_term_frequencies(c.phrase) for c in candidates] + [reference]
    document_count = len(documents)

    appearances = Counter()
    for document in documents:
        appearances.update(set(document))
    idf = {
        term: math.log(document_count / (1 + count)) + 1.0
        for term, count in appearances.items()
    }

    for candidate, document in zip(candidates, documents):
        candidate.relevance = _cosine(document, reference, idf)


def shortlist(candidates: list[Candidate], limit: int = RELEVANCE_SHORTLIST) -> list[Candidate]:
    """Top N by relevance -- the gate that protects the LLM stage from being
    handed hundreds of items at once."""
    return sorted(candidates, key=lambda c: c.relevance, reverse=True)[:limit]
