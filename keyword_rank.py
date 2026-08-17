"""Scores and ranks keyword candidates. Pure arithmetic, no I/O, no model
call -- the LLM supplies semantic features (see llm.judge_keywords), this
module decides the ordering.

That split is deliberate. An LLM asked to rank a list returns a different
order run to run, can't be unit tested, and re-tuning it costs an API call
against a 20/day budget. A scoring function over LLM-provided features is
reproducible, testable, and tunable for free -- and when a bad keyword lands
at #1 you can see exactly which feature put it there.

Every feature is normalized to [0,1] before weighting. Without that, weights
are uninterpretable (0.3 means nothing when one feature ranges 0-15 and
another 0-1) and length-biased features quietly dominate: a raw transcript
hit count makes the same keyword score higher on a 60-minute video than a
3-minute one, which measures video length, not keyword quality.
"""

import math
import re
from dataclasses import dataclass, field

from candidates import LANE_COMPETITOR, LANE_DEMAND, LANE_SUPPLY, Candidate

# Weights. Tunable without touching logic and without spending an API call --
# the entire point of keeping ranking out of the model. Sum is not required to
# be 1.0; scores are only ever compared against each other.
W_RELEVANCE = 0.30
W_SPECIFICITY = 0.25      # highest single non-relevance weight, on purpose:
                          # a small channel cannot win broad terms, so long-tail
                          # specificity is the only realistic path to ranking
W_COVERAGE = 0.20
W_AUTOCOMPLETE = 0.15
W_INTENT = 0.10
W_COMPETITOR = 0.05       # deliberately smallest -- see consensus gate below

# Planning mode: the video does not exist yet, so "does this video deliver on
# the keyword" is either meaningless (no script pasted) or means the OPPOSITE
# of what it means for a published video. For a live video, low coverage is a
# warning -- don't target what you barely discuss, retention will punish it.
# For a draft, low coverage is an OPPORTUNITY -- real demand the script does
# not address yet, i.e. something to go write.
#
# With no script there is nothing to measure at all, so coverage's weight is
# redistributed rather than left in place: leaving W_COVERAGE at 0.20 while
# every candidate scores 0.0 would not be neutral, it would compress the
# whole score range and let the remaining features fight over a smaller
# spread. Demand and specificity absorb it, since with no content to match
# against they are the only signals carrying real information.
W_COVERAGE_PLANNING_NO_SCRIPT = 0.0
W_AUTOCOMPLETE_PLANNING_NO_SCRIPT = W_AUTOCOMPLETE + 0.10
W_SPECIFICITY_PLANNING_NO_SCRIPT = W_SPECIFICITY + 0.10

# Below this, a candidate is dropped before scoring, not merely down-weighted.
# Found by real bug, not chosen in the abstract: a long, well-suggested but
# entirely off-topic phrase ("jinnah international airport" turning up as
# primary for a video with nothing to do with Karachi) can accumulate enough
# specificity + autocomplete-position score to outrank genuinely relevant
# keywords, because those two features say nothing about topical fit -- only
# `relevance` does, and at W_RELEVANCE=0.30 it can be outvoted by the other
# five features combined. A weighting fix does not close this gap reliably
# because the other features are unbounded in how much they can compensate;
# only a hard floor guarantees a keyword this unrelated can never surface as
# a recommendation. Set from real data: a full candidate pool's median
# relevance sits around 0.08-0.10 (autocomplete's a-z sweep is mostly noise),
# while genuinely on-topic candidates in a working run scored 0.4-0.58 -- 0.20
# sits well above the noise floor and below real signal.
RELEVANCE_FLOOR = 0.20

# A tag on a competitor's video is that creator's unvalidated guess, not
# evidence. One competitor using a phrase is noise; several independently
# using it is a real signal about the niche's vocabulary. Below this many
# distinct competitors, the signal is discarded rather than down-weighted.
COMPETITOR_CONSENSUS_MIN = 2

# Autocomplete positions past this are treated as equally weak rather than
# finely distinguished -- the difference between rank 1 and 3 is meaningful,
# between 18 and 20 is noise.
AUTOCOMPLETE_RANK_FLOOR = 10

# Search intent weights. Informational scores highest because YouTube is
# overwhelmingly a "teach me / show me" surface; transactional queries
# usually convert better on a web page than on a video.
INTENT_WEIGHTS = {
    "informational": 1.0,
    "comparison": 0.85,
    "navigational": 0.5,
    "transactional": 0.4,
    "unknown": 0.5,
}

# Coverage: where a keyword appears matters as much as whether it appears.
# A phrase in the title is a promise; the same phrase once at minute 47 is a
# passing mention. Ranking for a keyword the video barely delivers on earns
# bad retention, which YouTube punishes -- so this is a promise-keeping
# check, not just another relevance score.
#
# The description is split the same way: a real bug, found by comparing
# against a real channel's historical CTR data, was a keyword ("scholarships
# for international students in france") winning primary over the video's
# actual subject (university rankings) because "scholarships" appeared once,
# in a throwaway list near the end of the description -- treated as equally
# strong evidence as the opening sentence, which is where a creator almost
# always actually states the video's subject. Splitting into opening/rest
# fixes that: a word only in the rest of the description can no longer
# outweigh a word that's genuinely the stated topic.
COVERAGE_TITLE_WEIGHT = 1.0
COVERAGE_DESCRIPTION_OPENING_WEIGHT = 0.6
COVERAGE_DESCRIPTION_REST_WEIGHT = 0.15
COVERAGE_EARLY_TRANSCRIPT_WEIGHT = 0.8   # first EARLY_FRACTION of the video
COVERAGE_LATE_TRANSCRIPT_WEIGHT = 0.3
EARLY_FRACTION = 0.25

# How much of the description counts as "opening" -- the first sentence,
# capped at this many characters so one long run-on sentence can't swallow
# the whole description into the high-weight bucket.
COVERAGE_OPENING_MAX_CHARS = 160
_SENTENCE_END_PATTERN = re.compile(r"[.!?]\s")


def _split_opening(text: str, max_chars: int = COVERAGE_OPENING_MAX_CHARS) -> tuple[str, str]:
    """(opening, rest). Opening ends at the first sentence boundary or
    max_chars, whichever comes first -- falls back to a flat character cut
    when there's no sentence-ending punctuation at all (common in short,
    caption-style descriptions) rather than treating the whole text as
    "opening" by default."""
    if not text:
        return "", ""
    match = _SENTENCE_END_PATTERN.search(text)
    end = match.end() if match else len(text)
    end = min(end, max_chars)
    return text[:end], text[end:]

# Function words ignored when measuring coverage: their presence or absence
# says nothing about whether the video covers a topic.
_COVERAGE_STOPWORDS = {
    "a", "an", "the", "for", "to", "of", "in", "on", "is", "are", "and", "or",
    "with", "from", "at", "by", "it", "do", "does", "how", "what", "why",
    "should", "i", "you", "my", "your", "be", "can", "get",
}

_GENERIC_WORDS = {
    "tips", "guide", "tutorial", "best", "top", "new", "video", "how", "what",
    "why", "review", "explained", "full", "complete", "easy", "simple", "free",
    "2024", "2025", "2026", "viral", "trending", "shorts",
}


@dataclass
class ScoredKeyword:
    candidate: Candidate
    score: float
    specificity: float
    coverage: float
    autocomplete_strength: float
    intent: str
    intent_weight: float
    evidence: list[str] = field(default_factory=list)
    competition: float | None = None   # only ever set for finalists

    @property
    def phrase(self) -> str:
        return self.candidate.phrase


def specificity(phrase: str) -> float:
    """[0,1]. How narrowly this phrase targets one thing.

    A small channel cannot outrank established ones on broad terms, so this
    is weighted heavily: "study abroad" is unwinnable, "aps certificate
    germany requirements" is reachable. Built from word count (longer =
    narrower, saturating at 5), and penalized by the share of words that are
    generic filler.
    """
    words = phrase.split()
    if not words:
        return 0.0
    length_component = min(len(words), 5) / 5.0
    generic_share = sum(1 for w in words if w in _GENERIC_WORDS) / len(words)
    return max(0.0, length_component * (1.0 - generic_share))


def autocomplete_strength(rank: int | None) -> float:
    """[0,1]. Ordinal position strength, NOT search volume.

    Google orders suggestions by something popularity-adjacent, but that
    ordering is also shaped by personalization, freshness, and prefix
    matching. There is no free source of real YouTube search volume -- naming
    and treating this as ordinal strength is the honest option.
    """
    if rank is None:
        return 0.0
    if rank >= AUTOCOMPLETE_RANK_FLOOR:
        return 0.0
    return (AUTOCOMPLETE_RANK_FLOOR - rank) / AUTOCOMPLETE_RANK_FLOOR


def _content_words(phrase: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9']+", phrase.lower()) if w not in _COVERAGE_STOPWORDS]


def _phrase_overlap(phrase: str, text: str) -> float:
    """[0,1] fraction of the keyword's content words present in text.

    Word-level rather than exact-substring on purpose: a description reading
    "the APS certificate for students going to Germany" genuinely does cover
    the keyword "aps certificate germany", but an exact match finds nothing
    and would report the video as not covering its own subject.
    """
    if not text or not phrase:
        return 0.0
    words = _content_words(phrase)
    if not words:
        return 0.0
    haystack = text.lower()
    return sum(1 for w in words if re.search(rf"\b{re.escape(w)}", haystack)) / len(words)


def content_coverage(
    phrase: str,
    title: str,
    description: str,
    transcript_segments: list | None = None,
    transcript_text: str | None = None,
) -> float:
    """[0,1]. Whether the video actually delivers on this keyword, weighted by
    where it appears rather than how many times.

    Uses timestamped segments when available so an early mention counts for
    more than a late one; falls back to plain text (position-blind, still
    density-normalized) when there is no timing data. The description gets
    the same early/late split -- a word only in the opening sentence carries
    a video's stated subject, a word only later on is a passing mention (see
    the comment above COVERAGE_DESCRIPTION_OPENING_WEIGHT for the real case
    this fixes).
    """
    phrase = phrase.lower().strip()
    if not phrase:
        return 0.0

    score = 0.0
    score += COVERAGE_TITLE_WEIGHT * _phrase_overlap(phrase, title)
    opening, rest = _split_opening(description)
    score += COVERAGE_DESCRIPTION_OPENING_WEIGHT * _phrase_overlap(phrase, opening)
    score += COVERAGE_DESCRIPTION_REST_WEIGHT * _phrase_overlap(phrase, rest)

    if transcript_segments:
        starts = [getattr(s, "start", 0.0) for s in transcript_segments]
        duration = max(starts) if starts else 0.0
        cutoff = duration * EARLY_FRACTION
        early_text = " ".join(
            getattr(s, "text", "") or "" for s in transcript_segments
            if getattr(s, "start", 0.0) <= cutoff
        )
        late_text = " ".join(
            getattr(s, "text", "") or "" for s in transcript_segments
            if getattr(s, "start", 0.0) > cutoff
        )
        score += COVERAGE_EARLY_TRANSCRIPT_WEIGHT * _phrase_overlap(phrase, early_text)
        score += COVERAGE_LATE_TRANSCRIPT_WEIGHT * _phrase_overlap(phrase, late_text)
    elif transcript_text:
        score += COVERAGE_LATE_TRANSCRIPT_WEIGHT * _phrase_overlap(phrase, transcript_text)

    maximum = (
        COVERAGE_TITLE_WEIGHT + COVERAGE_DESCRIPTION_OPENING_WEIGHT + COVERAGE_DESCRIPTION_REST_WEIGHT
        + COVERAGE_EARLY_TRANSCRIPT_WEIGHT + COVERAGE_LATE_TRANSCRIPT_WEIGHT
    )
    return min(1.0, score / maximum)


def competitor_strength(hits: int) -> float:
    """[0,1], consensus-gated. Returns 0 below COMPETITOR_CONSENSUS_MIN
    distinct competitors rather than a small non-zero score: a single
    competitor's tag is one person's guess and should carry no weight at
    all, not merely little weight."""
    if hits < COMPETITOR_CONSENSUS_MIN:
        return 0.0
    return min(1.0, hits / 5.0)


def _build_evidence(
    candidate: Candidate, coverage: float, intent: str,
    planning: bool = False, has_script: bool = True,
) -> list[str]:
    """Human-readable reasons this keyword was chosen. The output is supposed
    to read like a consultant's reasoning, not an oracle's list -- a keyword
    with no statable reason behind it is exactly the "suggestion because it
    was told to produce suggestions" problem this pipeline exists to fix.

    The coverage line is the one that changes meaning in planning mode: for a
    published video "you don't cover this" is a reason NOT to target it, but
    for a draft it is the most actionable line in the report -- go cover it.
    """
    evidence = []
    if candidate.autocomplete_rank is not None:
        evidence.append(f"YouTube suggests this at position {candidate.autocomplete_rank + 1}")
    if candidate.competitor_hits >= COMPETITOR_CONSENSUS_MIN:
        evidence.append(f"{candidate.competitor_hits} competing videos target it")

    if planning and not has_script:
        pass  # nothing to measure against; claiming any coverage verdict would be invented
    elif planning:
        if coverage >= 0.5:
            evidence.append("your draft already covers this well")
        elif coverage > 0:
            evidence.append("your draft touches this only briefly — worth expanding")
        else:
            evidence.append("your draft doesn't mention this yet — worth covering")
    else:
        if coverage >= 0.5:
            evidence.append("your video covers this prominently")
        elif coverage > 0:
            evidence.append("mentioned in your video, but only briefly")
        else:
            evidence.append("your video does not currently cover this")

    if LANE_SUPPLY in candidate.lanes and LANE_DEMAND in candidate.lanes:
        evidence.append("matches both what you say and what people search")
    if intent and intent != "unknown":
        evidence.append(f"{intent} intent")
    return evidence


def rank_keywords(
    candidates: list[Candidate],
    title: str,
    description: str,
    transcript_segments: list | None = None,
    transcript_text: str | None = None,
    intents: dict[str, str] | None = None,
    enforce_floor: bool = True,
    planning: bool = False,
) -> list[ScoredKeyword]:
    """Ranks candidates by the weighted sum of normalized features.

    intents maps phrase -> intent label, supplied by the LLM judge. Missing
    entries fall back to "unknown" so the ranker still produces a full
    ordering when the model call failed entirely.

    enforce_floor=False skips the RELEVANCE_FLOOR cut. This exists for the
    orchestrator's degraded fallback path ONLY (see keyword_pipeline.run) --
    when literally nothing clears the floor, showing nothing is worse than
    showing the closest matches with an honest low-confidence label. This
    function's own default stays strict; opting out is the caller's explicit
    decision, made visible, not a silent relaxation.

    planning=True means the video does not exist yet. With no draft script,
    coverage is unmeasurable and its weight is redistributed (see
    W_COVERAGE_PLANNING_NO_SCRIPT); with a draft script, coverage is still
    scored but reads as opportunity rather than warning in the evidence.
    """
    intents = intents or {}
    scored: list[ScoredKeyword] = []
    has_script = bool(transcript_segments or transcript_text)

    if planning and not has_script:
        w_coverage = W_COVERAGE_PLANNING_NO_SCRIPT
        w_specificity = W_SPECIFICITY_PLANNING_NO_SCRIPT
        w_autocomplete = W_AUTOCOMPLETE_PLANNING_NO_SCRIPT
    else:
        w_coverage = W_COVERAGE
        w_specificity = W_SPECIFICITY
        w_autocomplete = W_AUTOCOMPLETE

    for candidate in candidates:
        if enforce_floor and candidate.relevance < RELEVANCE_FLOOR:
            continue  # dropped outright, not down-weighted -- see RELEVANCE_FLOOR
        spec = specificity(candidate.phrase)
        cov = content_coverage(
            candidate.phrase, title, description, transcript_segments, transcript_text
        )
        strength = autocomplete_strength(candidate.autocomplete_rank)
        intent = intents.get(candidate.phrase, "unknown")
        intent_weight = INTENT_WEIGHTS.get(intent, INTENT_WEIGHTS["unknown"])
        competitor = competitor_strength(candidate.competitor_hits)

        score = (
            W_RELEVANCE * candidate.relevance
            + w_specificity * spec
            + w_coverage * cov
            + w_autocomplete * strength
            + W_INTENT * intent_weight
            + W_COMPETITOR * competitor
        )

        scored.append(ScoredKeyword(
            candidate=candidate,
            score=score,
            specificity=spec,
            coverage=cov,
            autocomplete_strength=strength,
            intent=intent,
            intent_weight=intent_weight,
            evidence=_build_evidence(candidate, cov, intent, planning, has_script),
        ))

    return sorted(scored, key=lambda k: k.score, reverse=True)


# ------------------------------------------------------------------- strategy

PRIMARY_COUNT = 1
SECONDARY_COUNT = 4
LONGTAIL_MIN_WORDS = 4


@dataclass
class KeywordStrategy:
    primary: ScoredKeyword | None
    secondary: list[ScoredKeyword]
    long_tail: list[ScoredKeyword]
    lanes_used: list[str]
    confidence: str
    confidence_reason: str

    @property
    def all_keywords(self) -> list[ScoredKeyword]:
        return ([self.primary] if self.primary else []) + self.secondary + self.long_tail


def assess_confidence(lanes_used: list[str], candidate_count: int) -> tuple[str, str]:
    """Confidence reflects which evidence lanes actually fired, so a result
    built on one degraded source never looks as authoritative as one built on
    three. The app degrades gracefully everywhere else; without this, that
    degradation is invisible to the person reading the output."""
    missing = []
    if LANE_DEMAND not in lanes_used:
        missing.append("no YouTube search suggestions (endpoint unavailable)")
    if LANE_SUPPLY not in lanes_used:
        # Covers two different causes (no transcript given, or one given but
        # with no reusable phrase in it) with one honest label -- "no
        # transcript" specifically was wrong in the second case and read as
        # "you forgot to paste one" when the user hadn't.
        missing.append("no reusable phrases from the transcript/script")
    if LANE_COMPETITOR not in lanes_used:
        missing.append("competitor comparison was off")

    if not missing and candidate_count >= 20:
        return "high", "Built from search demand, your transcript, and competing videos."
    if len(missing) >= 2 or candidate_count < 10:
        return "low", "Limited evidence: " + "; ".join(missing) + "."
    return "medium", "Partial evidence: " + "; ".join(missing) + "."


def build_strategy(ranked: list[ScoredKeyword], lanes_used: list[str]) -> KeywordStrategy:
    """Splits a ranked list into a primary/secondary/long-tail hierarchy.

    Long-tail is selected by word count rather than by score position: the
    point of a long-tail set is reachability for a small channel, and those
    phrases legitimately rank lower on broad-appeal signals like autocomplete
    strength while being the most winnable targets available.
    """
    confidence, reason = assess_confidence(lanes_used, len(ranked))
    if not ranked:
        return KeywordStrategy(None, [], [], lanes_used, confidence, reason)

    # Primary is the best HEAD term, not simply the top-scoring phrase. The
    # top scorer is often a long question ("is aps certificate required for
    # indian students"), which is a fine long-tail target but a poor primary
    # keyword -- a primary is what the title and description get built
    # around, so it has to be short enough to actually use that way.
    head_terms = [k for k in ranked if k.candidate.word_count < LONGTAIL_MIN_WORDS]
    primary = head_terms[0] if head_terms else ranked[0]

    remaining = [k for k in ranked if k.phrase != primary.phrase]
    secondary = [k for k in remaining if k.candidate.word_count < LONGTAIL_MIN_WORDS][:SECONDARY_COUNT]
    chosen = {k.phrase for k in secondary}
    long_tail = [
        k for k in remaining
        if k.phrase not in chosen and k.candidate.word_count >= LONGTAIL_MIN_WORDS
    ][:8]

    return KeywordStrategy(
        primary=primary,
        secondary=secondary,
        long_tail=long_tail,
        lanes_used=lanes_used,
        confidence=confidence,
        confidence_reason=reason,
    )


def head_term_phrases(strategy: KeywordStrategy) -> list[str]:
    """Primary + secondary only -- deliberately excludes long_tail.

    This is the bridge between the keyword strategy and llm.py's tags list.
    Tags are a terse, hidden YouTube field; long-tail entries are often full
    questions ("is aps certificate required for indian students"), which are
    good guidance for a description or title but a poor fit as a literal tag.
    Head terms (primary/secondary) are short phrases either way, so they
    merge into tags without changing what a "tag" looks like.
    """
    if strategy.primary is None:
        return []
    return [strategy.primary.phrase] + [k.phrase for k in strategy.secondary]


def merge_into_tags(existing_tags: list[str], strategy: KeywordStrategy) -> list[str]:
    """Appends any head-term keyword not already covered by an existing tag,
    case-insensitively. Order preserved, existing tags always come first, so
    a caller enforcing a character budget (llm.enforce_tag_char_limit) drops
    from the newly-added end first rather than displacing what Gemini itself
    already generated.
    """
    existing_lower = {t.lower() for t in existing_tags}
    additions = [t for t in head_term_phrases(strategy) if t.lower() not in existing_lower]
    return existing_tags + additions


def format_keyword_evidence(strategy: KeywordStrategy) -> str:
    """Formats the strategy into the prompt block llm.generate_seo injects
    for real search-demand grounding. Deliberately plain text, not JSON --
    this is read by the model as context, not parsed by anything, and plain
    prose keeps it consistent with the rest of the user prompt.

    Kept in keyword_rank.py rather than llm.py so llm.py never has to import
    keyword_rank's types -- the boundary between "how keywords are found and
    scored" and "how the SEO copy gets written" stays one-directional.
    """
    if strategy.primary is None:
        return ""

    lines = [
        "Real search demand (from live YouTube search suggestions and "
        "competing videos, not a guess):",
        f"- Primary keyword: \"{strategy.primary.phrase}\" "
        f"({'; '.join(strategy.primary.evidence)})",
    ]
    for keyword in strategy.secondary:
        lines.append(f"- Secondary: \"{keyword.phrase}\" ({'; '.join(keyword.evidence)})")
    return "\n".join(lines)


CONTENT_GAP_MAX_COVERAGE = 0.35
CONTENT_GAP_MIN_DEMAND = 0.3


def content_gaps(strategy: KeywordStrategy, limit: int = 6) -> list[ScoredKeyword]:
    """Planning-mode output: real search demand the draft does NOT address yet.

    This is the inversion that makes planning different from analysis. For a
    published video, high demand + low coverage is a keyword to avoid -- you
    would be promising something the video does not deliver. For a draft, the
    same pair is the single most actionable thing in the report: proven
    demand, and you still have time to go write that section.

    Requires real demand (an autocomplete position) rather than just low
    coverage -- otherwise this would surface every irrelevant phrase the
    video happens not to mention, which is most of them.
    """
    return sorted(
        (
            k for k in strategy.all_keywords
            if k.coverage <= CONTENT_GAP_MAX_COVERAGE
            and k.autocomplete_strength >= CONTENT_GAP_MIN_DEMAND
        ),
        key=lambda k: k.autocomplete_strength,
        reverse=True,
    )[:limit]
