"""Full-pipeline backtest against REAL per-video search attribution.

Follow-on to eval_relevance_floor.py, which only tested the relevance floor
against a channel-wide export and a GUESSED best-matching video. This uses
per-video Studio exports the channel owner provided (Archive 2/), which name
the real video each search term drove views to -- no guessing, no API/OAuth
needed on this end since the exports were pulled manually from Studio.

THE QUESTION
------------
For each real video, does keyword_pipeline.run()'s actual "primary keyword"
output -- the full system: relevance, specificity, coverage, autocomplete,
competitor consensus, and the LLM judge -- match what genuinely drove clicks
to THAT SPECIFIC video? This is stronger evidence than eval_relevance_floor.py:
that eval tested one cutoff against a guessed video; this tests the real
ranked output against the real video.

PROVIDER SPLIT
--------------
Videos are split across Gemini and DeepSeek (forced via keyword_pipeline's
deepseek_api_key parameter) to see whether the judge call's provider changes
outcomes. Worth being precise about what this can and can't show: the ONLY
LLM call in the ranking path is judge_keywords() (keep/reject + intent
labels) -- relevance, specificity, coverage and the final weighted score are
pure Python, identical regardless of provider. So this tests whether the
judge's classification differs enough between providers to change which
keyword tops the ranking, not two different ranking systems.

Split is alternating by view count (highest video -> group A, next -> group
B, ...) so neither group is accidentally stacked with big or small videos.

EXCLUDED VIDEOS
----------------
2 of the 15 exports have zero named search terms (all views fell into
YouTube's unnamed "Other" bucket) -- nothing to compare the app's output
against, so they are skipped rather than spending model calls with no way to
score the result.

WHAT THIS CANNOT SHOW
----------------------
n=13, one channel. Not causality (no A/B), not generalisation, and a
"correct" result here is scored on whether the app's OWN pipeline would have
surfaced the real term at all (relevance floor, judge keep/reject) and
whether it ranked highly -- not whether ranking it would have caused MORE
views than the video already got. This is the same honest limitation
eval_relevance_floor.py states, carried over rather than dropped for a
bigger-sounding result.

USAGE
    python3 eval_pipeline_backtest.py plan     # print the video/provider assignment, no API calls
    python3 eval_pipeline_backtest.py run      # execute the real backtest (costs real API calls)
"""

import json
import os
import sys

import requests
from dotenv import load_dotenv

import keyword_pipeline
from eval_relevance_floor import appears_in_title, load_search_terms
from keywords import stem_words
from llm import understand_video
from transcript import TranscriptSegment, fetch_transcript_segments, segments_to_text
from youtube import fetch_metadata

RESULTS_CACHE = "eval_pipeline_backtest_results.json"
RESULTS_DEEPSEEK_CACHE = "eval_pipeline_backtest_results_deepseek.json"
RESULTS_SUPADATA_CACHE = "eval_pipeline_backtest_results_supadata.json"

# Transcripts fetched via Supadata, cached to disk. Cached deliberately: every
# fetch costs a credit, and a re-run of the eval must not silently re-spend
# them just because the harness was invoked twice.
TRANSCRIPT_CACHE = "eval_transcripts_supadata.json"

_SUPADATA_URL = "https://api.supadata.ai/v1/youtube/transcript"

# native ONLY, never "auto" or "generate". Those modes fall back to paid AI
# transcription (2 credits per MINUTE of video, vs 1 credit flat for native),
# which is a silent cost escalation on any video whose captions are missing.
# A video without real captions must fail here and be reported, not quietly
# transcribed at 10-50x the price.
_SUPADATA_MODE = "native"

# (video_id, Studio export folder, real total views on that export). Folder
# names are literal directory names under "Archive 2/" -- resolved by
# search.list against the channel once; hardcoded here so re-running this
# script never spends that quota again. The WES USA video appears once even
# though the export folder was duplicated on disk (byte-identical CSVs).
#
# The two zero-search-term exports (Unlock High-Paying Clinical Psychologist,
# Apply for MS in Europe with Low GPA) are deliberately absent: nothing to
# score them against.
VIDEOS = [
    ("tGSp6hZBgls", "Traffic source 2025-07-21_2026-08-19 Top MBA Universities in Dubai  | Best MBA Colleges in UAE", 1754),
    ("K7cf7wuZ3jo", 'Traffic source 2025-03-14_2026-08-19 "WES USA Latest Updates & Step-by-Step Process for Credential Evaluation | LetzStudy"', 606),
    ("ve9nRwk_pyk", "Traffic source 2025-07-17_2026-08-19 Top Masters Universities in Dubai by That You Must Consider!", 432),
    ("eKwKznJNWx4", "Traffic source 2025-07-14_2026-08-19 University of Birmingham Dubai_ Complete Success Guide  🎓 |  Courses, Campus Life", 414),
    ("RBjsnkrWs8o", 'Traffic source 2025-05-28_2026-08-19 "🎓 Study Law in Dubai | Explore Legal Education with LetzStudy"', 341),
    ("m7pGyZT7Izk", "Traffic source 2025-07-20_2026-08-19 MBBS in Dubai Fees | Tuition Costs Explained", 325),
    ("9KnjZjQ5vJA", "Traffic source 2025-07-02_2026-08-19 Top-Ranked Universities for Automobile Engineering  | Best Global Colleges !", 298),
    ("McX7iu13Y_k", "Traffic source 2025-07-08_2026-08-19 Discover the University of Wollongong in Dubai – Your Future Starts Here!", 224),
    ("5jDMF3BAT9g", 'Traffic source 2025-04-02_2026-08-19 "Top Universities in Malaysia_ Your Guide to Study Abroad & Success | LetzStudy"', 102),
    ("U7FnCX2Tlpk", 'Traffic source 2025-08-18_2026-08-19 "Nanyang Technological University NTU_ Ultimate Guide You Can’t Miss."', 93),
    ("D9DogMNU4EA", 'Traffic source 2025-09-15_2026-08-19 "Top Public Universities in the UK Ranked  – Shocking Results!"', 68),
    ("0uHeWKnZZpA", "Traffic source 2026-01-02_2026-08-19 Is Marine Engineering Worth It? A Practical Guide to Marine Engineering", 25),
    ("hGN5qUgx-Os", 'Traffic source 2025-06-29_2026-08-19 "Top Universities in the UK for International Students | Study in the UK"', 14),
]

ARCHIVE_DIR = "Archive 2"


def assign_providers(videos: list[tuple[str, str, int]]) -> dict[str, str]:
    """{video_id: "gemini" | "deepseek"}, alternating by view rank so neither
    group is stacked with disproportionately big or small videos."""
    ranked = sorted(videos, key=lambda v: -v[2])
    return {
        video_id: ("gemini" if i % 2 == 0 else "deepseek")
        for i, (video_id, _, _) in enumerate(ranked)
    }


def print_plan() -> None:
    assignment = assign_providers(VIDEOS)
    gemini = [v for v in VIDEOS if assignment[v[0]] == "gemini"]
    deepseek = [v for v in VIDEOS if assignment[v[0]] == "deepseek"]
    print(f"{len(VIDEOS)} videos, {len(gemini)} Gemini / {len(deepseek)} DeepSeek\n")
    for label, group in (("GEMINI", gemini), ("DEEPSEEK", deepseek)):
        print(f"{label}:")
        for video_id, folder, views in group:
            title = folder.split("_2026-08-19 ", 1)[-1].strip('"“”')
            print(f"  {views:>5} views  {video_id}  {title[:60]}")
        print()
    print("2 calls/video (understand_video + judge_keywords).")
    print(f"Gemini requests (typical): {len(gemini) * 2}")
    print(f"DeepSeek requests (typical): {len(deepseek) * 2}  (falls back to Gemini only on DeepSeek failure)")


def _load_transcript_cache() -> dict:
    if os.path.exists(TRANSCRIPT_CACHE):
        with open(TRANSCRIPT_CACHE) as handle:
            return json.load(handle)
    return {}


def fetch_transcript_supadata(video_id: str, api_key: str, cache: dict) -> list | None:
    """Real official captions via Supadata, as TranscriptSegment objects.

    Exists because youtube_transcript_api started returning IpBlocked partway
    through this session -- confirmed blanket (an unrelated control video was
    blocked too), not per-video. That is the documented fragility of an
    unofficial endpoint, and it made the before/after comparison this eval
    depends on impossible to run.

    Returns None rather than raising, and never falls back to AI generation
    (see _SUPADATA_MODE): a missing transcript is a reportable fact here, not
    something to paper over with a costlier substitute whose text would not
    be comparable to the other videos' anyway.
    """
    if video_id in cache:
        payload = cache[video_id]
    else:
        response = requests.get(
            _SUPADATA_URL,
            headers={"x-api-key": api_key},
            params={"videoId": video_id, "mode": _SUPADATA_MODE},
            timeout=30,
        )
        if response.status_code != 200:
            print(f"    supadata {response.status_code}: {response.text[:120]}")
            return None
        payload = response.json()
        cache[video_id] = payload
        with open(TRANSCRIPT_CACHE, "w") as handle:
            json.dump(cache, handle)

    content = payload.get("content")
    if not isinstance(content, list):
        return None
    return [
        TranscriptSegment(
            start=item["offset"] / 1000,      # Supadata reports milliseconds;
            duration=item["duration"] / 1000,  # TranscriptSegment expects seconds
            text=item["text"],
        )
        for item in content
    ]


def _stems(phrase: str) -> set[str]:
    return set(stem_words(phrase))


def matches_real_term(candidate_phrase: str, real_term: str) -> bool:
    """Whether an app-produced phrase represents the same search as a real
    term. Deliberately strict, because this function IS the measurement --
    every coverage percentage this harness reports is its output.

    The earlier version required only that 60% of the smaller stem set was
    contained in the larger. That silently inflated every number: stopwords
    are stripped before comparison, so "your malaysia" reduces to the single
    stem {malaysia} and matched ANY Malaysia phrase --

        "your malaysia" == "study in malaysia"      (reported as a hit)
        "your malaysia" == "malaysia visa cost"     (also a hit)
        "your malaysia" == "malaysia weather today" (also a hit)

    Those are three different searches. One shared content word is a topic in
    common, not a query in common, so it now only counts when that word is
    the WHOLE of both phrases ("uowd" vs "uowd"). Beyond that, two shared
    content words are required before the 60% rule is consulted at all.

    Consequence worth stating plainly: this reports LOWER coverage than the
    previous version on identical data. The previous numbers were wrong.
    """
    a, b = _stems(candidate_phrase), _stems(real_term)
    if not a or not b:
        return False

    shared = a & b
    if len(shared) < 2:
        # A single common word only means the same search when neither phrase
        # carries anything else -- "think uowd" is not the query "uowd".
        return a == b
    return len(shared) / min(len(a), len(b)) >= 0.6


def evaluate_video(
    video_id: str, folder: str, provider: str, api_keys: list[str],
    deepseek_key: str | None, transcript_cache: dict | None = None,
    supadata_key: str | None = None, use_llm_entities: bool = True,
) -> dict:
    real_terms = load_search_terms(os.path.join(ARCHIVE_DIR, folder, "Table data.csv"))
    total_real_views = sum(v for _, v in real_terms)

    meta = fetch_metadata(video_id, os.getenv("YOUTUBE_API_KEY"))
    if supadata_key is not None:
        # `transcript_cache or {}` would be a bug here: an EMPTY dict is
        # falsy, so the first call would substitute a fresh throwaway dict,
        # every video would write only its own entry, and the on-disk cache
        # would end up holding just the last one -- re-spending a credit per
        # video on every subsequent run. Identity check, not truthiness.
        if transcript_cache is None:
            transcript_cache = {}
        segments = fetch_transcript_supadata(video_id, supadata_key, transcript_cache)
    else:
        segments = fetch_transcript_segments(video_id)
    transcript_text = segments_to_text(segments) if segments else None

    use_key = deepseek_key if provider == "deepseek" else None
    understanding = understand_video(
        api_keys=api_keys, title=meta.title, description=meta.description,
        existing_tags=meta.tags, transcript=transcript_text, comments=[],
        deepseek_api_key=use_key,
    )
    pipeline_result = keyword_pipeline.run(
        api_keys=api_keys, content_summary=understanding.content_summary,
        title=meta.title, description=meta.description, existing_tags=meta.tags,
        transcript=transcript_text, transcript_segments=segments,
        competitors=None, deepseek_api_key=use_key,
        # None forces the capitalised-run regex, which is the control arm.
        # Both arms run minutes apart in one session on purpose: autocomplete
        # is a live endpoint that drifted enough earlier today to move a video
        # from 99% to 10% with no code change at all, so a baseline measured
        # hours ago cannot be compared against.
        llm_entities=understanding.entities if use_llm_entities else None,
    )
    strategy = pipeline_result.strategy
    app_phrases = [k.phrase for k in strategy.all_keywords]

    scored_terms = []
    matched_views = 0
    for term, views in real_terms:
        trivial = appears_in_title(term, meta.title)
        found = any(matches_real_term(p, term) for p in app_phrases)
        if found:
            matched_views += views
        scored_terms.append({"term": term, "views": views, "trivial": trivial, "found_by_app": found})

    primary_matches_top_real_term = bool(
        real_terms and strategy.primary
        and matches_real_term(strategy.primary.phrase, real_terms[0][0])
    )

    return {
        "video_id": video_id, "title": meta.title, "provider": provider,
        "app_primary": strategy.primary.phrase if strategy.primary else None,
        "app_secondary": [k.phrase for k in strategy.secondary],
        "confidence": strategy.confidence,
        "top_real_term": real_terms[0][0] if real_terms else None,
        "top_real_term_views": real_terms[0][1] if real_terms else 0,
        "primary_matches_top_real_term": primary_matches_top_real_term,
        "total_real_views": total_real_views,
        "matched_views": matched_views,
        "coverage": matched_views / total_real_views if total_real_views else 0.0,
        "terms": scored_terms,
    }


def run() -> None:
    load_dotenv()
    api_keys = [k for k in [os.getenv("GEMINI_API_KEY"), os.getenv("GEMINI_API_KEY_2")] if k]
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_keys:
        raise SystemExit("GEMINI_API_KEY is not set.")

    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    use_supadata = command.startswith("run-supadata")
    supadata_key = os.getenv("SUPADATA_API_KEY") if use_supadata else None
    if use_supadata and not supadata_key:
        raise SystemExit("SUPADATA_API_KEY is not set.")
    transcript_cache = _load_transcript_cache() if use_supadata else None

    # "-control" suffix runs the identical eval with the regex entity
    # extractor, for a same-session A/B against autocomplete drift.
    use_llm_entities = not command.endswith("-control")
    force_provider = "deepseek" if command.startswith(("run-deepseek", "run-supadata")) else None
    cache_path = (
        (RESULTS_SUPADATA_CACHE.replace(".json", "_control.json") if not use_llm_entities
         else RESULTS_SUPADATA_CACHE) if use_supadata
        else RESULTS_DEEPSEEK_CACHE if force_provider
        else RESULTS_CACHE
    )
    assignment = (
        {video_id: force_provider for video_id, _, _ in VIDEOS}
        if force_provider else assign_providers(VIDEOS)
    )

    results = []
    for video_id, folder, views in VIDEOS:
        provider = assignment[video_id]
        print(f"  {provider:>8}  {video_id}  ({views} views)  ...", end=" ", flush=True)
        try:
            result = evaluate_video(
                video_id, folder, provider, api_keys, deepseek_key,
                transcript_cache=transcript_cache, supadata_key=supadata_key,
                use_llm_entities=use_llm_entities,
            )
            print(f"primary={result['app_primary']!r}  coverage={result['coverage']:.0%}")
            results.append(result)
        except Exception as exc:
            print(f"FAILED: {exc}")
            results.append({"video_id": video_id, "provider": provider, "error": str(exc)})

    with open(cache_path, "w") as handle:
        json.dump(results, handle, indent=2)
    print(f"\nwrote {len(results)} results -> {cache_path}")
    report(results)


def report(results: list[dict]) -> None:
    ok = [r for r in results if "error" not in r]
    failed = [r for r in results if "error" in r]
    print(f"\n{len(ok)}/{len(results)} videos scored" + (f", {len(failed)} failed" if failed else ""))

    for provider in ("gemini", "deepseek"):
        group = [r for r in ok if r["provider"] == provider]
        if not group:
            continue
        top_hits = sum(r["primary_matches_top_real_term"] for r in group)
        avg_coverage = sum(r["coverage"] for r in group) / len(group)
        print(f"\n{provider.upper()}  ({len(group)} videos)")
        print(f"  primary keyword matched the #1 real search term : {top_hits}/{len(group)}")
        print(f"  average view-coverage of real terms found       : {avg_coverage:.0%}")

    print("\nPer video:")
    for r in ok:
        marker = "MATCH" if r["primary_matches_top_real_term"] else "miss "
        print(
            f"  [{marker}] [{r['provider']:>8}] {r['title'][:45]:45}  "
            f"real_top={r['top_real_term']!r}  app_primary={r['app_primary']!r}"
        )
    for r in failed:
        print(f"  [FAILED ] {r['video_id']}  {r['error']}")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "plan"
    if command == "plan":
        print_plan()
    elif command.startswith(("run", "run-deepseek", "run-supadata")):
        run()
    else:
        raise SystemExit(__doc__)
