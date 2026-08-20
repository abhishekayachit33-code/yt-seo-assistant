"""Assembles the full report bundle -- the analysis/plan result plus every
derived signal (health score, audience gap, shelf life, CTA placement,
readability, pacing, projected reach, revenue, playbook, checklist, keyword
strategy) -- as one JSON-serializable dict.

This is the part of app.py that ran INLINE after generate_seo() returned,
computed fresh every time render_report() was called (lines ~1692-1783 of
the old script). It has to move server-side rather than be recomputed in
the frontend: it's pure Python business logic with zero UI concerns, same
as everything else this migration is porting rather than rewriting.
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from analytics import PROJECTION_DAYS, project_views, summarize_performance
from competitors import audience_gap
from cta import analyze_ctas
from keyword_rank import KeywordStrategy, ScoredKeyword
from keywords import estimate_spoken_length
from limits import compute_health_score, extract_hashtags
from pacing import SILENT_GAP_THRESHOLD_SECONDS, find_silent_gaps, words_per_minute_blocks
from playbook import build_playbook, build_preproduction_checklist
from readability import scan_readability
from revenue import estimate_revenue
from seo_diff import diff_description, diff_tags
from shelf_life import classify
from youtube import VideoMeta


def _keyword_out(k: ScoredKeyword) -> dict:
    return {
        "phrase": k.phrase,
        "score": k.score,
        "specificity": k.specificity,
        "coverage": k.coverage,
        "autocomplete_strength": k.autocomplete_strength,
        "relevance": k.candidate.relevance,
        "intent": k.intent,
        "evidence": k.evidence,
        "autocomplete_rank": k.candidate.autocomplete_rank,
        "competitor_hits": k.candidate.competitor_hits,
    }


def _keyword_strategy_out(strategy: KeywordStrategy | None) -> dict | None:
    if strategy is None:
        return None
    return {
        "primary": _keyword_out(strategy.primary) if strategy.primary else None,
        "secondary": [_keyword_out(k) for k in strategy.secondary],
        "long_tail": [_keyword_out(k) for k in strategy.long_tail],
        "lanes_used": strategy.lanes_used,
        "confidence": strategy.confidence,
        "confidence_reason": strategy.confidence_reason,
    }


def build_report(
    meta: VideoMeta,
    result: dict,
    *,
    top_comments: list[str] | None = None,
    competitors: list | None = None,
    include_competitors: bool = False,
    transcript_text: str | None = None,
    transcript_segments: list | None = None,
    live: bool = True,
    note: str = "",
    planning: bool = False,
    keyword_strategy: KeywordStrategy | None = None,
    thumbnail_review: dict | None = None,
    variants: list[tuple[str, dict]] | None = None,
) -> dict:
    """One-shot equivalent of app.py's post-generate_seo block. Returns
    everything the old render_report() needed, keyed the same way the
    frontend's report screens are being built against."""
    original_score, _ = compute_health_score(
        meta.title, meta.description, meta.tags, extract_hashtags(meta.description)
    )
    titles = result.get("titles", [])
    optimized_score, optimized_rules = compute_health_score(
        titles[0] if titles else meta.title,
        result.get("description", ""), result.get("tags", []), result.get("hashtags", []),
    )

    gap = None
    if include_competitors and competitors:
        gap = audience_gap(meta.view_count, list(meta.tags) + result.get("tags", []), competitors)

    shelf = classify(meta.title, meta.tags, transcript_text)
    cta_report = analyze_ctas(transcript_segments) if live else None
    speech_estimate = estimate_spoken_length(transcript_text)
    readability = scan_readability(transcript_text)

    performance = projection = revenue = None
    if live and not planning:
        performance = summarize_performance(
            meta.view_count, meta.like_count, meta.comment_count, meta.published_at,
        )
        projection = project_views(
            meta.view_count, performance.views_per_day, optimized_score - original_score,
        )
        revenue = estimate_revenue(
            meta.view_count, meta.category_id,
            projection.low_views - projection.baseline_views,
            projection.high_views - projection.baseline_views,
        )

    playbook = build_playbook(optimized_rules, gap, cta_report, shelf, thumbnail_review) if live else []

    checklist = None
    if planning:
        checklist = build_preproduction_checklist(
            optimized_score, result.get("hook_analysis", {}), speech_estimate, shelf,
        )

    tag_diff = diff_tags(meta.tags, result.get("tags", [])) if live else None
    description_diff = diff_description(meta.description, result.get("description", "")) if live else []

    pacing = None
    if transcript_segments:
        blocks = words_per_minute_blocks(transcript_segments)
        wpm = [b.wpm for b in blocks]
        gaps = find_silent_gaps(transcript_segments)
        pacing = {
            "average_wpm": round(sum(wpm) / len(wpm)) if wpm else 0,
            "blocks": [{"minute": b.minute, "wpm": b.wpm} for b in blocks],
            "silent_gap_threshold_seconds": SILENT_GAP_THRESHOLD_SECONDS,
            "silent_gaps": [
                {"start": g.start, "end": g.end, "duration": g.duration} for g in gaps
            ],
        }

    return {
        "video_id": meta.video_id,
        "title": meta.title,
        "channel": meta.channel_title,
        "thumbnail_url": meta.thumbnail_url,
        "live": live,
        "planning": planning,
        "note": note,
        "result": result,
        "original_score": original_score,
        "optimized_score": optimized_score,
        "optimized_rules": [
            {"label": r.label, "passed": r.passed, "detail": r.detail} for r in optimized_rules
        ],
        "audience_gap": (
            {
                "competitor_median_views": gap.competitor_median_views,
                "gap": gap.gap,
                "has_outliers": gap.has_outliers,
                "missing_tags": [{"tag": t, "competitor_count": n} for t, n in gap.missing_tags],
                "top_competitors": [
                    {
                        "video_id": c.video_id, "title": c.title, "channel_title": c.channel_title,
                        "tags": c.tags, "view_count": c.view_count,
                    }
                    for c in gap.top_competitors
                ],
                "outliers": [
                    {
                        "video_id": c.video_id, "title": c.title, "channel_title": c.channel_title,
                        "view_count": c.view_count,
                    }
                    for c in gap.outliers
                ],
            }
            if gap is not None else None
        ),
        "shelf_life": {
            "evergreen_score": shelf.evergreen_score, "classification": shelf.classification,
            "expectation": shelf.expectation, "evergreen_hits": shelf.evergreen_hits,
            "trending_hits": shelf.trending_hits, "is_unclassified": shelf.is_unclassified,
        },
        "cta_report": (
            {
                "duration": cta_report.duration,
                "recommended_timestamp": cta_report.recommended_timestamp,
                "has_well_placed": cta_report.has_well_placed,
                "mentions": [
                    {
                        "seconds": m.seconds, "position": m.position, "label": m.label,
                        "text": m.text, "zone": m.zone, "timestamp": m.timestamp,
                    }
                    for m in cta_report.mentions
                ],
                "stranded": [
                    {"timestamp": m.timestamp, "label": m.label, "position": m.position}
                    for m in cta_report.stranded
                ],
            }
            if cta_report is not None else None
        ),
        "readability": (
            {
                "filler_hits": [{"word": h.word, "count": h.count} for h in readability.filler_hits],
                "total_filler_count": readability.total_filler_count,
                "word_count": readability.word_count,
                "sentence_count": readability.sentence_count,
                "avg_sentence_length": readability.avg_sentence_length,
                "filler_rate": readability.filler_rate,
            }
            if readability is not None else None
        ),
        "speech_estimate": (
            {
                "word_count": speech_estimate.word_count,
                "low_minutes": speech_estimate.low_minutes,
                "high_minutes": speech_estimate.high_minutes,
                "label": speech_estimate.label,
            }
            if speech_estimate is not None else None
        ),
        "pacing": pacing,
        "performance": (
            {
                "views": performance.views, "likes": performance.likes,
                "comments": performance.comments, "days_since_upload": performance.days_since_upload,
                "views_per_day": performance.views_per_day, "engagement_rate": performance.engagement_rate,
            }
            if performance is not None else None
        ),
        "projection": (
            {
                "projection_days": PROJECTION_DAYS, "score_delta": projection.score_delta,
                "low_uplift": projection.low_uplift, "high_uplift": projection.high_uplift,
                "baseline_views": projection.baseline_views, "low_views": projection.low_views,
                "high_views": projection.high_views,
            }
            if projection is not None else None
        ),
        "revenue": (
            {
                "current": revenue.current, "category_name": revenue.category_name,
                "rpm": revenue.rpm, "additional_low": revenue.additional_low,
                "additional_high": revenue.additional_high, "is_known_category": revenue.is_known_category,
            }
            if revenue is not None else None
        ),
        "playbook": [{"title": a.title, "detail": a.detail, "icon": a.icon} for a in playbook],
        "preproduction_checklist": (
            {
                "ready_to_record": checklist.ready_to_record,
                "items": [
                    {"label": i.label, "status": i.status, "detail": i.detail}
                    for i in checklist.items
                ],
            }
            if checklist is not None else None
        ),
        "tag_diff": (
            {"added": tag_diff.added, "kept": tag_diff.kept, "removed": tag_diff.removed}
            if tag_diff is not None else None
        ),
        "description_diff": description_diff,
        "top_comments": top_comments or [],
        "keyword_strategy": _keyword_strategy_out(keyword_strategy),
        "variants": (
            [{"title": t, "result": r} for t, r in variants] if variants else None
        ),
    }
