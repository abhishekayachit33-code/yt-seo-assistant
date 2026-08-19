"""Negative validation of RELEVANCE_FLOOR against real search demand.

Standalone analysis tool, deliberately NOT imported by the app -- same shape
and reasoning as yt_analytics_pull.py.

THE QUESTION
------------
keyword_rank.RELEVANCE_FLOOR drops a candidate outright rather than
down-weighting it. That threshold was set from one incident, never measured.
This asks the only question about it that has a real answer available:

    of the search terms that DEMONSTRABLY drove views to this channel,
    how many would the floor have thrown away?

A term in the export is not a guess. Someone typed it into YouTube, clicked
this channel's video, and watched. If the pipeline would have discarded that
term as insufficiently relevant, the floor is too aggressive, and no amount
of reasoning about the constant outranks that.

WHY THIS EVAL AND NOT A BACKTEST
--------------------------------
Per-video attribution is not available at this channel's volume: YouTube
privacy-buckets low-volume queries, and 85.1% of search views land in an
unnamed "Other" (447 named terms explain 1,988 of 13,312). A backtest needs
to know which video each term drove; this does not. It asks each term against
its BEST-matching video across the channel, which is deliberately generous --
the pipeline is given the most favourable pairing available, so a term that
still fails is failing decisively.

THE CIRCULARITY CONTROL, WHICH IS NOT OPTIONAL
----------------------------------------------
About half this channel's real search terms are entity names ("university of
birmingham dubai"). If the video is titled "University of Birmingham Dubai --
Full Review", the pipeline "finds" that term because it is reading the title
back to itself. Counting those as successes measures the creator's titling
habit, not the pipeline -- exactly the circular result that was caught and
reversed once already in this project's history.

So every number here is reported twice: TRIVIAL (the term already appears in
the matched video's own title) and EARNED (it does not). Only the earned
column says anything about whether the pipeline works.

WHAT THIS CANNOT SHOW
---------------------
Causality, generalisation beyond one study-abroad channel, or that the six
ranking weights are correct. With 34 terms above 10 views this detects a
broken floor, not a better one. It is a smoke test, and calling it validation
would repeat the mistake it exists to avoid.

USAGE
    python3 eval_relevance_floor.py fetch     # cache channel videos (~6 quota units)
    python3 eval_relevance_floor.py run       # score terms, print the report
"""

import csv
import json
import os
import re
import sys

import requests

from candidates import Candidate, score_relevance
from keyword_rank import RELEVANCE_FLOOR
from keywords import stem_words

CHANNEL_ID = "UCM9BIwHTLH-91w5kXsTcbQw"  # LetzStudy; 51,153 views matches the export
VIDEO_CACHE = "eval_channel_videos.json"

# The YouTube Studio export. Rows look like "YT_SEARCH.<query>" with the bare
# query repeated in "Source title".
DEFAULT_TERMS_CSV = (
    "Traffic source 2013-08-22_2026-08-17 LetzStudy-3/Table data.csv"
)
_SEARCH_PREFIX = "YT_SEARCH."

# Terms below this are kept in the corpus but reported separately: a single
# view is as likely to be an accident as a signal, and letting hundreds of
# 1-view rows dominate an average would drown the terms that carry real
# traffic.
MEANINGFUL_VIEWS = 10


def load_search_terms(path: str = DEFAULT_TERMS_CSV) -> list[tuple[str, int]]:
    """[(term, views)] from the Studio export, descending by views."""
    if not os.path.exists(path):
        raise SystemExit(
            f"Search-terms export not found at:\n  {path}\n\n"
            "Export it from YouTube Studio -> Analytics -> Advanced mode -> "
            "Traffic source -> YouTube search, then re-run."
        )
    rows: list[tuple[str, int]] = []
    with open(path, newline="") as handle:
        for row in csv.DictReader(handle):
            source = row.get("Traffic source", "")
            if not source.startswith(_SEARCH_PREFIX):
                continue
            term = (row.get("Source title") or source[len(_SEARCH_PREFIX):]).strip().lower()
            try:
                views = int(row.get("Views") or 0)
            except ValueError:
                continue
            if term:
                rows.append((term, views))
    return sorted(rows, key=lambda item: -item[1])


def fetch_channel_videos(api_key: str, channel_id: str = CHANNEL_ID) -> list[dict]:
    """Every upload's title and description, via the uploads playlist.
    ~1 quota unit per 50 videos -- far cheaper than search.list at 100 each."""
    channel = requests.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={"part": "contentDetails", "id": channel_id, "key": api_key},
        timeout=15,
    )
    channel.raise_for_status()
    items = channel.json().get("items", [])
    if not items:
        raise SystemExit(f"No channel found for {channel_id}")
    uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    videos: list[dict] = []
    page_token = ""
    while True:
        response = requests.get(
            "https://www.googleapis.com/youtube/v3/playlistItems",
            params={
                "part": "snippet", "playlistId": uploads, "maxResults": 50,
                "pageToken": page_token, "key": api_key,
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        for item in payload.get("items", []):
            snippet = item["snippet"]
            videos.append({
                "video_id": snippet.get("resourceId", {}).get("videoId", ""),
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
            })
        page_token = payload.get("nextPageToken", "")
        if not page_token:
            break
    return videos


def appears_in_title(term: str, title: str) -> bool:
    """Circularity control: is this term already sitting in the video's own
    title? Compared on stems so "university"/"universities" and singular/plural
    do not read as different, and as a subset rather than a substring so word
    order and filler words ("in", "for") do not hide a match."""
    term_stems = set(stem_words(term))
    if not term_stems:
        return False
    return term_stems <= set(stem_words(title))


def best_match(term: str, videos: list[dict]) -> tuple[dict | None, float]:
    """(video, relevance) for the video this term scores highest against.

    Deliberately the MAXIMUM over the whole channel rather than the true
    attributed video, which the export does not provide. That is generous to
    the pipeline on purpose: it hands every term its most favourable possible
    pairing, so a term failing the floor here would have failed against its
    real video too.
    """
    best_video, best_score = None, 0.0
    for video in videos:
        candidate = Candidate(phrase=term)
        reference = f"{video['title']}\n{video['description'][:1000]}"
        score_relevance([candidate], reference)
        if candidate.relevance > best_score:
            best_video, best_score = video, candidate.relevance
    return best_video, best_score


def evaluate(
    terms: list[tuple[str, int]], videos: list[dict], floor: float = RELEVANCE_FLOOR
) -> dict:
    """Scores every term and splits the results by the circularity control."""
    trivial, earned = [], []
    for term, views in terms:
        video, relevance = best_match(term, videos)
        record = {
            "term": term, "views": views, "relevance": round(relevance, 4),
            "survives": relevance >= floor,
            "video_title": video["title"] if video else "",
        }
        (trivial if video and appears_in_title(term, video["title"]) else earned).append(record)
    return {"trivial": trivial, "earned": earned, "floor": floor}


def _summarize(label: str, records: list[dict]) -> None:
    if not records:
        print(f"  {label}: none")
        return
    total_views = sum(r["views"] for r in records)
    cut = [r for r in records if not r["survives"]]
    cut_views = sum(r["views"] for r in cut)
    print(f"  {label}")
    print(f"    terms                : {len(records)}  ({total_views:,} views)")
    print(f"    CUT by the floor     : {len(cut)}  ({len(cut)/len(records):.0%} of terms)")
    print(
        f"    views behind the cut : {cut_views:,}"
        + (f"  ({cut_views/total_views:.0%} of this bucket)" if total_views else "")
    )


def report(result: dict, min_views: int = MEANINGFUL_VIEWS) -> None:
    floor = result["floor"]
    print(f"\nRELEVANCE_FLOOR = {floor}\n")
    print("Terms that really drove views, scored against their best-matching video.")
    print("EARNED is the only column that says anything about the pipeline;")
    print("TRIVIAL terms are already in the video's own title.\n")

    for scope, predicate in (
        (f"ALL TERMS", lambda r: True),
        (f"TERMS WITH >={min_views} VIEWS", lambda r: r["views"] >= min_views),
    ):
        print(f"{scope}")
        _summarize("EARNED  (not in the title)", [r for r in result["earned"] if predicate(r)])
        _summarize("TRIVIAL (already in title)", [r for r in result["trivial"] if predicate(r)])
        print()

    lost = sorted(
        (r for r in result["earned"] if not r["survives"] and r["views"] >= min_views),
        key=lambda r: -r["views"],
    )
    if lost:
        print(f"Highest-traffic EARNED terms the floor would have discarded:")
        for r in lost[:15]:
            print(f"  {r['views']:>4} views  rel={r['relevance']:.3f}  {r['term']}")
            print(f"              best match: {r['video_title'][:70]}")


def sweep(terms: list[tuple[str, int]], videos: list[dict]) -> None:
    """What the floor costs at each candidate value, in real views."""
    print("\nFloor sensitivity (EARNED terms only, >=%d views):" % MEANINGFUL_VIEWS)
    print(f"  {'floor':>6}  {'terms kept':>10}  {'views kept':>11}")
    scored = evaluate(terms, videos, floor=0.0)
    earned = [r for r in scored["earned"] if r["views"] >= MEANINGFUL_VIEWS]
    total = sum(r["views"] for r in earned)
    for value in (0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30):
        kept = [r for r in earned if r["relevance"] >= value]
        kept_views = sum(r["views"] for r in kept)
        marker = "  <- current" if abs(value - RELEVANCE_FLOOR) < 1e-9 else ""
        share = f"{kept_views/total:.0%}" if total else "n/a"
        print(f"  {value:>6.2f}  {len(kept):>10}  {kept_views:>7,} ({share}){marker}")


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "run"

    if command == "fetch":
        from dotenv import load_dotenv
        load_dotenv()
        api_key = os.getenv("YOUTUBE_API_KEY")
        if not api_key:
            raise SystemExit("YOUTUBE_API_KEY is not set.")
        videos = fetch_channel_videos(api_key)
        with open(VIDEO_CACHE, "w") as handle:
            json.dump(videos, handle)
        print(f"cached {len(videos)} videos -> {VIDEO_CACHE}")
        return

    if not os.path.exists(VIDEO_CACHE):
        raise SystemExit(f"No {VIDEO_CACHE}. Run: python3 {sys.argv[0]} fetch")
    with open(VIDEO_CACHE) as handle:
        videos = json.load(handle)
    terms = load_search_terms()
    print(f"{len(terms)} real search terms; {len(videos)} channel videos")

    result = evaluate(terms, videos)
    report(result)
    if command == "sweep":
        sweep(terms, videos)


if __name__ == "__main__":
    main()
