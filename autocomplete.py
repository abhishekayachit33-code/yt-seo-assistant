"""Demand-side evidence: what people actually type into YouTube search.

Everything else this app extracts is supply-side -- what the video says about
itself. Autocomplete is the only signal here that comes from viewers rather
than from the creator, which is what makes it worth the fragility.

Fragility is real and deliberate to accept: this is Google's undocumented
suggest endpoint, not part of the YouTube Data API. No key, no quota, no SLA,
and it can rate-limit or disappear without notice. Every function here
degrades to an empty list rather than raising, so a blocked endpoint costs
the demand lane and nothing else.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import requests

_SUGGEST_URL = "https://suggestqueries.google.com/complete/search"

# Region/language matter more than they look: the same seed returns different
# suggestions per market, and this app's users are targeting Indian audiences.
# Leaving these at Google's US default would return demand data for the wrong
# country entirely.
DEFAULT_REGION = "IN"
DEFAULT_LANGUAGE = "en"

_TIMEOUT_SECONDS = 5
_MAX_WORKERS = 8

# Hard ceiling on HTTP calls per analysis. Seed expansion is combinatorial
# (seeds x modifiers), and this endpoint is unofficial and rate-limited --
# an uncapped expansion is how you get IP-blocked mid-demo. Budget is spent
# on the highest-priority seeds first (see build_queries).
MAX_QUERIES = 60

_ALPHABET = "abcdefghijklmnopqrstuvwxyz"

# Question and comparison forms surface intent that bare entity seeds never
# reach: "germany" alone never suggests "is germany good for indian students".
_QUESTION_PREFIXES = ("how to", "why", "is", "should i", "what is", "best")
_COMPARISON_SUFFIXES = ("vs", "or", "for beginners", "for indian students")


@dataclass
class Suggestion:
    """rank is the position Google returned this at (0-based) for its query.

    Deliberately NOT called 'demand' or 'volume'. Google orders suggestions by
    something popularity-adjacent, but it is also shaped by personalization,
    freshness, and prefix matching. Treating this as search volume would be
    inventing a number the API never gave us -- it is an ordinal strength
    signal and the naming has to keep saying so.
    """
    phrase: str
    rank: int
    seed: str


def build_queries(seeds: list[str], max_queries: int = MAX_QUERIES) -> list[str]:
    """Expands seeds into query strings, highest-value first, then truncates
    to the budget. Order matters because the truncation is a real cutoff:
    bare seeds are the most reliable, question/comparison forms surface
    intent, and the a-z sweep is the widest but noisiest, so it goes last and
    is the first thing dropped when the budget runs out."""
    queries: list[str] = []
    seen: set[str] = set()

    def add(query: str) -> None:
        query = query.strip()
        if query and query not in seen:
            seen.add(query)
            queries.append(query)

    for seed in seeds:
        add(seed)
    for seed in seeds:
        for prefix in _QUESTION_PREFIXES:
            add(f"{prefix} {seed}")
    for seed in seeds:
        for suffix in _COMPARISON_SUFFIXES:
            add(f"{seed} {suffix}")
    for seed in seeds:
        for letter in _ALPHABET:
            add(f"{seed} {letter}")

    return queries[:max_queries]


def fetch_suggestions(
    query: str, region: str = DEFAULT_REGION, language: str = DEFAULT_LANGUAGE
) -> list[str]:
    """One call to the suggest endpoint. Empty list on any failure -- a single
    blocked or malformed response must not take down the whole lane."""
    try:
        response = requests.get(
            _SUGGEST_URL,
            params={"client": "firefox", "ds": "yt", "q": query, "gl": region, "hl": language},
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        # Response is JSON but historically served as text/javascript, so it
        # is parsed explicitly rather than via response.json().
        payload = json.loads(response.text)
    except (requests.exceptions.RequestException, json.JSONDecodeError, ValueError):
        return []

    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
        return []
    return [s for s in payload[1] if isinstance(s, str)]


def collect(
    seeds: list[str],
    max_queries: int = MAX_QUERIES,
    region: str = DEFAULT_REGION,
    language: str = DEFAULT_LANGUAGE,
) -> list[Suggestion]:
    """Fans the expanded queries out in parallel and flattens the results.

    Parallel because this is 60 sequential HTTP calls otherwise, inside a
    Streamlit button click with a user watching a spinner -- serial would add
    30+ seconds to every analysis.

    When the same phrase comes back from several queries, the best (lowest)
    rank wins: a phrase Google puts first for any query is a stronger signal
    than the same phrase buried in another query's list.
    """
    if not seeds:
        return []

    queries = build_queries(seeds, max_queries)

    def _fetch(query: str) -> tuple[str, list[str]]:
        return query, fetch_suggestions(query, region, language)

    best: dict[str, Suggestion] = {}
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        for query, phrases in pool.map(_fetch, queries):
            for rank, phrase in enumerate(phrases):
                normalized = phrase.strip().lower()
                if not normalized:
                    continue
                existing = best.get(normalized)
                if existing is None or rank < existing.rank:
                    best[normalized] = Suggestion(phrase=normalized, rank=rank, seed=query)

    return sorted(best.values(), key=lambda s: s.rank)
