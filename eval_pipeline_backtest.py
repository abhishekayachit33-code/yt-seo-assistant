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

from dotenv import load_dotenv

import keyword_pipeline
from eval_relevance_floor import appears_in_title, load_search_terms
from keywords import stem_words
from llm import understand_video
from transcript import fetch_transcript_segments, segments_to_text
from youtube import fetch_metadata

RESULTS_CACHE = "eval_pipeline_backtest_results.json"
RESULTS_DEEPSEEK_CACHE = "eval_pipeline_backtest_results_deepseek.json"

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


def _stems(phrase: str) -> set[str]:
    return set(stem_words(phrase))


def matches_real_term(candidate_phrase: str, real_term: str) -> bool:
    """A loose but principled match: the smaller stem set is (mostly)
    contained in the larger one. Catches "top universities in the uk" against
    the real term "universities in uk" without requiring exact wording --
    the two genuinely mean the same search, just not byte-identical."""
    a, b = _stems(candidate_phrase), _stems(real_term)
    if not a or not b:
        return False
    smaller, larger = (a, b) if len(a) <= len(b) else (b, a)
    overlap = len(smaller & larger) / len(smaller)
    return overlap >= 0.6


def evaluate_video(video_id: str, folder: str, provider: str, api_keys: list[str], deepseek_key: str | None) -> dict:
    real_terms = load_search_terms(os.path.join(ARCHIVE_DIR, folder, "Table data.csv"))
    total_real_views = sum(v for _, v in real_terms)

    meta = fetch_metadata(video_id, os.getenv("YOUTUBE_API_KEY"))
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

    force_provider = "deepseek" if len(sys.argv) > 1 and sys.argv[1] == "run-deepseek" else None
    cache_path = RESULTS_DEEPSEEK_CACHE if force_provider else RESULTS_CACHE
    assignment = (
        {video_id: force_provider for video_id, _, _ in VIDEOS}
        if force_provider else assign_providers(VIDEOS)
    )

    results = []
    for video_id, folder, views in VIDEOS:
        provider = assignment[video_id]
        print(f"  {provider:>8}  {video_id}  ({views} views)  ...", end=" ", flush=True)
        try:
            result = evaluate_video(video_id, folder, provider, api_keys, deepseek_key)
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
    elif command in ("run", "run-deepseek"):
        run()
    else:
        raise SystemExit(__doc__)
