"""Orchestrates the keyword pipeline end to end: seeds -> evidence lanes ->
candidate pool -> cheap filter -> relevance cut -> LLM judge -> ranker ->
strategy.

Ordering here is a cost decision, not a style one. Free deterministic work
(seed building, filtering, TF-IDF relevance) runs first and cuts several
hundred candidates down to a few dozen; only then does anything spend a
Gemini call. Reversing that order would burn the daily quota judging phrases
a regex could have discarded.

Every lane is optional. A blocked suggest endpoint, a missing transcript, or
competitors left switched off each remove one source and lower the reported
confidence -- none of them stop a strategy being produced.
"""

import re
from dataclasses import dataclass

import autocomplete
from candidates import (
    LANE_COMPETITOR, LANE_DEMAND, LANE_SUPPLY,
    build_pool, score_relevance, shortlist,
)
from keyword_rank import KeywordStrategy, build_strategy, rank_keywords
from keywords import top_ngrams
from llm import judge_keywords

MAX_SEEDS = 6
SEED_MIN_CHARS = 4
TRANSCRIPT_EXCERPT_CHARS = 3000

_WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z'&-]+")

# Capitalised runs are the cheapest available proper-noun detector: "APS
# Certificate", "German Universities". Real entity recognition would mean
# adding spaCy and a model download to the Docker image for a gain this
# does not justify.
_ENTITY_PATTERN = re.compile(r"\b(?:[A-Z][a-zA-Z'&-]+|[A-Z]{2,})(?:\s+(?:[A-Z][a-zA-Z'&-]+|[A-Z]{2,}))*\b")

# Words that ruin a seed even when they appear prominently. Expanding any of
# these returns the whole internet rather than this video's niche. Wider than
# a normal stopword list on purpose -- it includes narration verbs and filler
# nouns ("explains", "process", "required") that survive stopword filtering
# but produce meaningless seeds like "video explains" or "process required".
_SEED_STOPLIST = {
    "video", "channel", "subscribe", "watch", "today", "welcome", "guys",
    "hello", "thanks", "please", "comment", "share", "like", "youtube",
    "explains", "explain", "covers", "cover", "shows", "show", "discusses",
    "including", "process", "required", "requires", "need", "needs", "want",
    "make", "makes", "made", "take", "takes", "give", "gives", "know",
    "learn", "understand", "help", "helps", "using", "used", "use", "way",
    "ways", "thing", "things", "lot", "much", "many", "well", "also",
    "viewer", "viewers", "watching", "audience", "people", "everyone",
    "step", "steps", "part", "parts", "first", "second", "third", "next",
    "important", "great", "good", "best", "better", "really", "actually",
}


def _entity_phrases(text: str) -> list[str]:
    """Capitalised multi-word runs, sentence-leading single words dropped.

    A capitalised word at the start of a sentence is usually just
    capitalisation, not an entity, so single-word matches are only kept when
    they are an acronym (APS, MBBS, IELTS) -- those are high-value seeds and
    always capitalised for a real reason.
    """
    found: list[str] = []
    for match in _ENTITY_PATTERN.findall(text or ""):
        phrase = match.strip()
        words = phrase.split()
        if len(words) > 1:
            found.append(phrase.lower())
        elif phrase.isupper() and len(phrase) >= 2:
            found.append(phrase.lower())
    return found


def _is_usable_seed(phrase: str) -> bool:
    words = phrase.split()
    if not words:
        return False
    # Any stoplisted word disqualifies the whole phrase: "aps process" is as
    # useless a search seed as "process" alone.
    return not any(w in _SEED_STOPLIST for w in words)


@dataclass
class PipelineResult:
    strategy: KeywordStrategy
    candidate_count: int          # size of the raw pool, before any cutting
    judged_count: int             # how many the LLM actually classified
    lanes_used: list[str]
    suggestions_found: int
    weak_evidence: bool = False   # True: nothing cleared RELEVANCE_FLOOR, shown anyway


def build_seeds(
    content_summary: str,
    title: str,
    existing_tags: list[str] | None = None,
    transcript: str | None = None,
    max_seeds: int = MAX_SEEDS,
) -> list[str]:
    """Seeds drive every downstream query, so they come from the richest
    description of the video available rather than the title alone.

    Capped hard: seed expansion is combinatorial against an unofficial,
    rate-limited endpoint (see autocomplete.MAX_QUERIES), so more seeds means
    shallower expansion per seed, not more total coverage.
    """
    seeds: list[str] = []
    seen: set[str] = set()

    def add(phrase: str) -> None:
        phrase = re.sub(r"\s+", " ", phrase.strip().lower())
        if len(phrase) >= SEED_MIN_CHARS and phrase not in seen and _is_usable_seed(phrase):
            seen.add(phrase)
            seeds.append(phrase)

    # Named entities first, from title and summary. These are the highest-
    # value seeds by a wide margin -- they are the specific things the video
    # is about, and they are what a viewer would actually type.
    for entity in _entity_phrases(title) + _entity_phrases(content_summary):
        add(entity)

    # The creator's own tags: already human-curated search phrases.
    for tag in (existing_tags or [])[:4]:
        add(tag)

    # Title bigrams as a fallback for titles with no capitalised entities.
    if title:
        words = [w.lower() for w in _WORD_PATTERN.findall(title) if len(w) > 3]
        for i in range(len(words) - 1):
            add(f"{words[i]} {words[i + 1]}")

    # Transcript bigrams last and only if still short: frequency is only
    # meaningful over a long text, so this is skipped for short inputs where
    # every bigram appears exactly once and the "top" ones are arbitrary.
    if transcript and len(seeds) < max_seeds and len(transcript.split()) > 200:
        for phrase, count in top_ngrams(transcript, 2, 8):
            if count > 2:
                add(phrase)

    return seeds[:max_seeds]


def _competitor_phrases(competitors: list) -> list[str]:
    """Titles and tags from competing videos, duplicates preserved -- the
    repeat count across distinct competitors is the consensus signal
    keyword_rank gates on.

    Titles are decomposed into 2- and 3-word phrases rather than used whole:
    a competitor's full title is not a search query, but the phrases inside
    it often are.
    """
    phrases: list[str] = []
    for competitor in competitors or []:
        title = getattr(competitor, "title", "") or ""
        for n in (3, 2):
            phrases.extend(phrase for phrase, _ in top_ngrams(title, n, 5))
        phrases.extend(t.lower() for t in (getattr(competitor, "tags", None) or []))
    return phrases


def run(
    api_keys: list[str],
    content_summary: str,
    title: str,
    description: str,
    existing_tags: list[str] | None = None,
    transcript: str | None = None,
    transcript_segments: list | None = None,
    competitors: list | None = None,
    use_llm_judge: bool = True,
    region: str = autocomplete.DEFAULT_REGION,
    planning: bool = False,
) -> PipelineResult:
    """planning=True: the video does not exist yet. Passed through to the
    ranker, which reweights and re-words coverage accordingly -- see
    keyword_rank.rank_keywords."""
    lanes_used: list[str] = []

    seeds = build_seeds(content_summary, title, existing_tags, transcript)

    # --- demand lane (free, unofficial, may return nothing) ---
    suggestions = autocomplete.collect(seeds, region=region) if seeds else []
    if suggestions:
        lanes_used.append(LANE_DEMAND)

    # --- supply lane (transcript n-grams) ---
    supply_phrases: list[str] = []
    if transcript:
        # count > 1 assumes a full video transcript, where natural repetition
        # is normal. A short planning-mode draft (a few hundred words) rarely
        # repeats any specific 2-3 word phrase twice, so that bar would zero
        # out the lane on real input. Below ~500 words, one occurrence is
        # legitimate supply evidence.
        word_count = len(re.findall(r"\S+", transcript))
        min_count = 1 if word_count < 500 else 2
        for n in (3, 2):
            supply_phrases.extend(
                phrase for phrase, count in top_ngrams(transcript, n, 25) if count >= min_count
            )
        if supply_phrases:
            lanes_used.append(LANE_SUPPLY)

    # --- competitor lane (opt-in upstream; costs YouTube search quota) ---
    competitor_phrases = _competitor_phrases(competitors)
    if competitor_phrases:
        lanes_used.append(LANE_COMPETITOR)

    pool = build_pool(supply_phrases, suggestions, competitor_phrases)
    candidate_count = len(pool)
    if not pool:
        return PipelineResult(
            strategy=build_strategy([], lanes_used),
            candidate_count=0, judged_count=0,
            lanes_used=lanes_used, suggestions_found=len(suggestions),
        )

    # Relevance is scored against the richest available description of the
    # video, not the title alone -- a one-line reference would score almost
    # everything at zero.
    reference = " ".join(filter(None, [
        content_summary, title, description[:1000],
        (transcript or "")[:TRANSCRIPT_EXCERPT_CHARS],
    ]))
    score_relevance(pool, reference)
    finalists = shortlist(pool)

    # --- LLM judge: features only, never an ordering ---
    judged: dict[str, dict] = {}
    if use_llm_judge and api_keys and content_summary:
        judged = judge_keywords(api_keys, content_summary, [c.phrase for c in finalists])

    if judged:
        kept = [c for c in finalists if judged.get(c.phrase, {}).get("keep", True)]
        # If the model rejected essentially everything, trust the deterministic
        # shortlist over a judgement that is more likely broken than correct.
        finalists = kept if len(kept) >= 5 else finalists

    intents = {phrase: verdict["intent"] for phrase, verdict in judged.items()}
    ranked = rank_keywords(
        finalists, title, description, transcript_segments, transcript, intents,
        planning=planning,
    )

    # Nothing cleared RELEVANCE_FLOOR. Rather than show an empty tab, fall
    # back to the closest matches anyway -- but only ever as an explicit,
    # visibly-flagged degradation (weak_evidence=True), never silently. This
    # is the one place enforce_floor=False is used in the whole app.
    weak_evidence = False
    if not ranked and finalists:
        weak_evidence = True
        ranked = rank_keywords(
            finalists, title, description, transcript_segments, transcript, intents,
            enforce_floor=False, planning=planning,
        )[:5]

    return PipelineResult(
        strategy=build_strategy(ranked, lanes_used),
        candidate_count=candidate_count,
        judged_count=len(judged),
        lanes_used=lanes_used,
        suggestions_found=len(suggestions),
        weak_evidence=weak_evidence,
    )
