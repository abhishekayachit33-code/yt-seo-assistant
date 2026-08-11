import os
from datetime import date

import altair as alt
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from analytics import PROJECTION_DAYS, project_views, summarize_performance
from comments import fetch_top_comments
from competitors import audience_gap, find_competitors
from cta import LATE_END, PRIME_END, PRIME_START, TOO_EARLY_BEFORE, analyze_ctas
from db import ensure_schema, get_analysis, get_cached_analysis, get_connection, list_recent, save_analysis
from export import build_csv_export, build_json_export, build_pdf_export
from keywords import estimate_spoken_length, top_ngrams
from limits import check_limits, compute_health_score, extract_hashtags
from llm import generate_seo
from pacing import SILENT_GAP_THRESHOLD_SECONDS, find_silent_gaps, words_per_minute_blocks
from playbook import build_playbook, build_preproduction_checklist
from readability import scan_readability
from revenue import estimate_revenue
from seo_diff import diff_description, diff_tags
from shelf_life import classify
from thumbnail import critique_thumbnail, critique_thumbnail_bytes
from transcript import fetch_transcript_segments, segments_to_text
from youtube import InvalidURLError, VideoNotFoundError, build_planned_meta, fetch_metadata, parse_video_id

load_dotenv()

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_KEYS = [k for k in [GEMINI_API_KEY, os.getenv("GEMINI_API_KEY_2")] if k]

st.set_page_config(
    page_title="YouTube SEO Studio",
    page_icon=":material/movie_filter:",
    layout="wide",
)


@st.cache_resource
def _db_connection():
    return get_connection()


def thumbnail_for(video_id: str) -> str:
    """YouTube's thumbnail URLs are deterministic from the video ID, so history
    entries can show artwork without spending any API quota."""
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def chips(items: list[str], color: str = "violet") -> None:
    """A wrapped row of native badges. Square brackets would break the badge
    markdown directive, so they are swapped for parentheses."""
    if not items:
        st.caption("None")
        return
    safe = (str(i).replace("[", "(").replace("]", ")") for i in items)
    st.markdown(" ".join(f":{color}-badge[{s}]" for s in safe))


# ---------------------------------------------------------------- header


def render_hero(video_id: str, title: str, channel: str, result: dict, note: str = "", planning: bool = False) -> None:
    score, rules = compute_health_score(
        title, result.get("description", ""), result.get("tags", []), result.get("hashtags", [])
    )
    passed = sum(r.passed for r in rules)

    with st.container(border=True):
        if planning:
            info = st.container()
        else:
            art, info = st.columns([1, 3], vertical_alignment="center")
            art.image(thumbnail_for(video_id), width="stretch")
        with info:
            st.markdown(f"### {title}")
            st.caption(":material/edit_note: Planned video — not yet uploaded" if planning else (f":material/account_circle: {channel}" if channel else ""))
            score_color = "green" if score >= 80 else "orange" if score >= 55 else "red"
            badges = (
                f":{score_color}-badge[:material/health_metrics: Health {score}%] "
                f":violet-badge[:material/sell: {len(result.get('tags', []))} tags] "
                f":blue-badge[:material/tag: {len(result.get('hashtags', []))} hashtags]"
            )
            if not planning:
                badges += f" :gray-badge[:material/segment: {len(result.get('chapters', []))} chapters]"
            st.markdown(badges)
            if note:
                st.caption(note)

    hard_limits = check_limits(
        title, result.get("description", ""), result.get("tags", []), result.get("hashtags", [])
    )
    failing = [c for c in hard_limits if not c.ok]
    if failing:
        st.warning(
            "Over YouTube's hard limit: " + ", ".join(f"{c.label} ({c.current:,}/{c.maximum:,})" for c in failing)
            + " — trim before publishing.",
            icon=":material/warning:",
        )

    with st.expander(f"Metadata health: {score}% ({passed}/{len(rules)} checks)", icon=":material/checklist:"):
        st.caption("Compliance against YouTube best practices and hard limits, not a guess.")
        for r in rules:
            icon = ":material/check_circle:" if r.passed else ":material/cancel:"
            color = "green" if r.passed else "red"
            st.markdown(f":{color}[{icon}] **{r.label}** — {r.detail}")
        st.divider()
        for c in hard_limits:
            icon = ":material/check_circle:" if c.ok else ":material/cancel:"
            color = "green" if c.ok else "red"
            st.markdown(f":{color}[{icon}] **{c.label}** — {c.current:,} / {c.maximum:,} limit")


# ---------------------------------------------------------------- sections


def render_variant_comparison(variants: list) -> None:
    with st.container(border=True):
        st.markdown("##### :material/compare_arrows: Title variants")
        st.caption("Each variant ran its own full analysis — its own generated tags, description, and hashtags.")
        columns = st.columns(len(variants))
        for column, (variant_title, variant_result) in zip(columns, variants):
            score, rules = compute_health_score(
                variant_title, variant_result.get("description", ""),
                variant_result.get("tags", []), variant_result.get("hashtags", []),
            )
            score_color = "green" if score >= 80 else "orange" if score >= 55 else "red"
            with column:
                with st.container(border=True, height="stretch"):
                    st.markdown(f"**{variant_title}**")
                    st.markdown(f":{score_color}-badge[:material/health_metrics: Health {score}%]")
                    st.caption(f"{len(variant_result.get('tags', []))} tags generated")
                    for r in rules:
                        icon = ":material/check_circle:" if r.passed else ":material/cancel:"
                        color = "green" if r.passed else "red"
                        st.markdown(f":{color}[{icon}] {r.label}")


def render_metadata(result: dict, existing_tags: list[str]) -> None:
    tags = result.get("tags", [])
    titles = result.get("titles", [])
    description = result.get("description", "")
    hashtags = result.get("hashtags", [])

    left, right = st.columns(2)

    with left:
        with st.container(border=True):
            st.markdown("##### :material/title: Title options")
            if titles:
                for i, t in enumerate(titles, 1):
                    over = len(t) > 100
                    st.markdown(f"**{i}.** {t}")
                    st.caption(f":{'red' if over else 'gray'}[{len(t)}/100 characters]")
                if result.get("titles_rationale"):
                    st.info(result["titles_rationale"], icon=":material/lightbulb:")
            else:
                st.caption("No title suggestions generated.")

        with st.container(border=True):
            st.markdown("##### :material/description: Optimized description")
            if description:
                st.text_area(
                    "Description", description, height=300,
                    label_visibility="collapsed", key="meta-description",
                )
            else:
                st.caption("No description generated.")

    with right:
        with st.container(border=True):
            joined = ", ".join(tags)
            st.markdown("##### :material/sell: Tags")
            st.caption(f"{len(tags)} tags · {len(joined)}/500 characters")

            existing_lower = {t.lower() for t in existing_tags}
            if existing_tags:
                kept = [t for t in tags if t.lower() in existing_lower]
                fresh = [t for t in tags if t.lower() not in existing_lower]
                st.markdown(f"**New suggestions** ({len(fresh)})")
                chips(fresh, "violet")
                st.markdown(f"**Kept from your video** ({len(kept)})")
                chips(kept, "gray")
            else:
                chips(tags, "violet")

            st.caption("Copy for the tags field")
            st.code(joined, language=None, wrap_lines=True)
            if result.get("tags_rationale"):
                st.info(result["tags_rationale"], icon=":material/lightbulb:")

        with st.container(border=True):
            st.markdown("##### :material/tag: Hashtags")
            st.caption(f"{len(hashtags)}/15 hashtags")
            chips(hashtags, "blue")
            st.code(" ".join(hashtags), language=None, wrap_lines=True)


def render_cta(report) -> None:
    with st.container(border=True):
        st.markdown("##### :material/campaign: Call-to-action placement")

        if report is None:
            st.caption("Needs a transcript, which was not available for this video.")
            return

        if not report.mentions:
            st.info(
                "No call to action found anywhere in the transcript — this video never asks "
                "viewers to subscribe, click, or sign up.",
                icon=":material/notifications_off:",
            )
            st.caption(f"The prime window for a first ask is around **{report.recommended_timestamp}**.")
            return

        for mention in report.stranded:
            st.warning(
                f"You asked viewers to **{mention.label}** at **{mention.timestamp}** "
                f"({mention.position:.0%} into the video), by which point most of the audience "
                f"has already clicked away. Move your main ask to around "
                f"**{report.recommended_timestamp}**, while they are still watching.",
                icon=":material/warning:",
            )
        if report.has_well_placed:
            st.success(
                "At least one ask lands in the prime window, where viewers are still watching "
                "and have seen enough to act on it.",
                icon=":material/check_circle:",
            )

        duration = report.duration
        zones = pd.DataFrame([
            {"start": 0.0, "end": TOO_EARLY_BEFORE * duration, "Zone": "Too early"},
            {"start": PRIME_START * duration, "end": PRIME_END * duration, "Zone": "Prime window"},
            {"start": PRIME_END * duration, "end": LATE_END * duration, "Zone": "Late"},
            {"start": LATE_END * duration, "end": duration, "Zone": "Too late"},
        ])
        bands = (
            alt.Chart(zones)
            .mark_rect(opacity=0.5)
            .encode(
                x=alt.X("start:Q", title="Seconds into the video"),
                x2="end:Q",
                color=alt.Color(
                    "Zone:N",
                    scale=alt.Scale(
                        domain=["Too early", "Prime window", "Late", "Too late"],
                        range=["#E0D6C4", "#B7D4BC", "#EBC9A6", "#E9B4A6"],
                    ),
                    legend=alt.Legend(orient="bottom", title=None),
                ),
                tooltip=["Zone:N"],
            )
        )
        marks = (
            alt.Chart(
                pd.DataFrame([
                    {"Seconds": m.seconds, "At": m.timestamp, "Ask": m.label, "Line": m.text[:80]}
                    for m in report.mentions
                ])
            )
            .mark_rule(size=2, color="#1C1917")
            .encode(x="Seconds:Q", tooltip=["At:N", "Ask:N", "Line:N"])
        )
        st.altair_chart((bands + marks).properties(height=90), width="stretch")

        st.dataframe(
            pd.DataFrame([
                {
                    "At": m.timestamp,
                    "Through": f"{m.position:.0%}",
                    "Ask": m.label,
                    "Placement": m.zone,
                    "Line": m.text,
                }
                for m in report.mentions
            ]),
            hide_index=True, width="stretch",
        )


def render_structure(result: dict, cta_report=None, live: bool = True, speech_estimate=None) -> None:
    chapters = result.get("chapters", [])
    hook = result.get("hook_analysis", {})

    left, right = st.columns(2)

    with left:
        with st.container(border=True):
            st.markdown("##### :material/segment: Chapters")
            if chapters:
                st.dataframe(
                    pd.DataFrame(
                        {
                            "Timestamp": [c.get("timestamp", "") for c in chapters],
                            "Chapter": [c.get("title", "") for c in chapters],
                        }
                    ),
                    hide_index=True, width="stretch",
                    column_config={"Timestamp": st.column_config.TextColumn(width="small")},
                )
                st.caption("Copy into your video description")
                st.code(
                    "\n".join(f"{c.get('timestamp', '')} {c.get('title', '')}" for c in chapters),
                    language=None,
                )
            else:
                st.caption("No chapters generated (transcript was not available).")

    with right:
        with st.container(border=True):
            st.markdown("##### :material/bolt: Hook analysis")
            verdict = hook.get("verdict", "")
            if verdict and verdict != "unavailable":
                st.markdown(f":orange-badge[:material/timer: First 30 seconds] **{verdict}**")
                if hook.get("reasoning"):
                    st.write(hook["reasoning"])
                if hook.get("rewrite"):
                    st.caption("Suggested rewrite for the opening")
                    st.info(hook["rewrite"], icon=":material/auto_fix_high:")
            else:
                st.caption("Hook analysis needs a transcript, which was not available for this video.")
            if speech_estimate is not None:
                st.caption(f":material/schedule: {speech_estimate.label}")

    if live:
        render_cta(cta_report)


def render_reach(performance, projection, original_score: int, optimized_score: int, revenue=None) -> None:
    with st.container(border=True):
        st.markdown("##### :material/rocket: Projected reach uplift")
        st.caption(
            "A heuristic, not a forecast: the metadata score improvement maps to an "
            "organic-search uplift band, applied to this video's own view velocity."
        )
        with st.container(horizontal=True):
            st.metric(
                "Metadata score", f"{optimized_score}%",
                delta=f"{optimized_score - original_score:+d} pts vs. original {original_score}%",
                border=True,
            )
            st.metric(
                "Projected search uplift",
                f"+{projection.low_uplift:.0%} – {projection.high_uplift:.0%}",
                delta="organic search reach", delta_color="off", border=True,
            )
            st.metric(
                f"Views in {PROJECTION_DAYS} days", f"{projection.low_views:,} – {projection.high_views:,}",
                delta=f"vs. {projection.baseline_views:,} at current pace",
                delta_color="off", border=True,
            )

        if projection.score_delta <= 0:
            st.caption(
                "The generated metadata did not score above the original, so no uplift is projected."
            )

        with st.expander("Current performance and revenue estimate", icon=":material/monitoring:"):
            with st.container(horizontal=True):
                st.metric("Total views", f"{performance.views:,}", border=True)
                st.metric(
                    "View velocity", f"{performance.views_per_day:,.0f}",
                    delta="per day", delta_color="off", border=True,
                )
                st.metric(
                    "Engagement rate", f"{performance.engagement_rate:.2f}%",
                    delta=f"{performance.likes:,} likes · {performance.comments:,} comments",
                    delta_color="off", border=True,
                    help="(likes + comments) ÷ views. Creators can hide like counts, in which case this reflects comments alone.",
                )
                st.metric(
                    "Age", f"{performance.days_since_upload:,}",
                    delta="days since upload", delta_color="off", border=True,
                )

            if revenue is not None:
                st.markdown("**Estimated AdSense revenue**")
                with st.container(horizontal=True):
                    st.metric(
                        "Earnings to date", f"${revenue.current:,.0f}",
                        delta=f"{revenue.category_name} · ${revenue.rpm:.2f} RPM",
                        delta_color="off", border=True,
                    )
                    st.metric(
                        f"Projected gain over {PROJECTION_DAYS} days",
                        f"+${revenue.additional_low:,.0f} – ${revenue.additional_high:,.0f}",
                        delta="if the SEO changes are applied", delta_color="off", border=True,
                    )
                st.caption(
                    "An order-of-magnitude estimate, not your earnings: a published average RPM "
                    "for this video's category applied to its view count. Pays nothing if the "
                    "channel is not in the Partner Programme."
                    + ("" if revenue.is_known_category else " This video's category is unrecognised, so a general average was used.")
                )


def render_shelf_life(shelf) -> None:
    with st.container(border=True):
        st.markdown("##### :material/hourglass: Shelf life")

        score = shelf.evergreen_score
        colour = "#166534" if score >= 55 else "#C2410C" if score <= 45 else "#B45309"
        ring = pd.DataFrame(
            {"part": ["Evergreen", "Trending"], "value": [score, 100 - score]}
        )
        gauge = (
            alt.Chart(ring)
            .mark_arc(innerRadius=58, outerRadius=80, cornerRadius=3)
            .encode(
                theta=alt.Theta("value:Q", stack=True),
                color=alt.Color(
                    "part:N",
                    scale=alt.Scale(domain=["Evergreen", "Trending"], range=[colour, "#D6CFC2"]),
                    legend=None,
                ),
                tooltip=["part:N", "value:Q"],
            )
        )
        label = (
            alt.Chart(pd.DataFrame({"text": [f"{score}%"]}))
            .mark_text(size=30, fontWeight="bold", color=colour)
            .encode(text="text:N")
        )
        st.altair_chart(gauge + label, width="stretch")

        st.markdown(f"**Classification: {shelf.classification}**")
        st.caption(shelf.expectation)

        if not shelf.is_unclassified:
            signal_left, signal_right = st.columns(2)
            with signal_left:
                st.markdown(":green-badge[Evergreen signals]")
                chips(shelf.evergreen_hits or [], "green")
            with signal_right:
                st.markdown(":orange-badge[Dating signals]")
                chips(shelf.trending_hits or [], "orange")


def render_analysis(
    result: dict,
    original_description: str = "",
    existing_tags: list[str] | None = None,
    transcript_text: str | None = None,
    transcript_segments=None,
    live: bool = True,
    performance=None,
    projection=None,
    original_score: int = 0,
    optimized_score: int = 0,
    shelf=None,
    revenue=None,
    readability=None,
) -> None:
    if live and performance is not None and projection is not None:
        render_reach(performance, projection, original_score, optimized_score, revenue)

    with st.container(border=True):
        st.markdown("##### :material/difference: Before vs. after")
        if not live:
            st.caption("Unavailable for a saved analysis. Re-run Analyze to see it.")
        else:
            tag_diff = diff_tags(existing_tags or [], result.get("tags", []))
            a, b, c = st.columns(3)
            a.metric("Tags added", len(tag_diff.added), border=True)
            b.metric("Tags kept", len(tag_diff.kept), border=True)
            c.metric("Tags dropped", len(tag_diff.removed), border=True)

            added_col, dropped_col = st.columns(2)
            with added_col:
                st.markdown("**Added**")
                chips(tag_diff.added, "green")
            with dropped_col:
                st.markdown("**Dropped**")
                chips(tag_diff.removed, "red")

            description_diff = diff_description(original_description, result.get("description", ""))
            if description_diff:
                with st.expander("Description changes", icon=":material/notes:"):
                    st.code("\n".join(description_diff), language="diff")

    if not live:
        st.caption(
            "Keyword density, pacing, and shelf life are computed from live video data, "
            "which is not stored with a saved analysis. Re-run Analyze to see them."
        )
        return

    with st.expander("More analysis: keywords, pacing, shelf life", icon=":material/query_stats:"):
        if shelf is not None:
            render_shelf_life(shelf)

        left, right = st.columns(2)

        with left:
            with st.container(border=True):
                st.markdown("##### :material/key: Keyword density")
                if not transcript_text:
                    st.caption("Needs a transcript, which was not available.")
                else:
                    mode = st.segmented_control(
                        "Phrase length", ["2-word phrases", "3-word phrases"],
                        default="2-word phrases", key="ngram-mode", label_visibility="collapsed",
                    )
                    n = 3 if mode == "3-word phrases" else 2
                    data = top_ngrams(transcript_text, n)
                    if data:
                        st.bar_chart(
                            pd.DataFrame({"phrase": [p for p, _ in data], "count": [c for _, c in data]}),
                            x="phrase", y="count", horizontal=True, height=380,
                        )
                    else:
                        st.caption("Not enough transcript text for this phrase length.")

        with right:
            with st.container(border=True):
                st.markdown("##### :material/speed: Speech pacing")
                if not transcript_segments:
                    st.caption("Needs a transcript, which was not available.")
                else:
                    blocks = words_per_minute_blocks(transcript_segments)
                    wpm = [b.wpm for b in blocks]
                    avg = round(sum(wpm) / len(wpm)) if wpm else 0
                    gaps = find_silent_gaps(transcript_segments)

                    m1, m2 = st.columns(2)
                    m1.metric("Average pace", f"{avg} wpm", border=True)
                    m2.metric("Silent gaps", len(gaps), delta=f">{SILENT_GAP_THRESHOLD_SECONDS:.0f}s", delta_color="off", border=True)

                    st.area_chart(
                        pd.DataFrame({"minute": [b.minute for b in blocks], "wpm": wpm}),
                        x="minute", y="wpm", height=260,
                    )
                    if gaps:
                        with st.expander(f"{len(gaps)} silent gap(s)", icon=":material/volume_off:"):
                            for g in gaps[:15]:
                                st.markdown(f"- **{g.start:.0f}s → {g.end:.0f}s** ({g.duration:.1f}s)")

        render_readability(readability)


def render_readability(report) -> None:
    with st.container(border=True):
        st.markdown("##### :material/spellcheck: Script readability")
        if report is None:
            st.caption("Needs a transcript or script, which was not available.")
            return
        m1, m2, m3 = st.columns(3)
        m1.metric("Filler words", report.total_filler_count, delta=f"{report.filler_rate}/100 words", delta_color="off", border=True)
        m2.metric("Avg. sentence length", f"{report.avg_sentence_length} words", border=True)
        m3.metric("Word count", f"{report.word_count:,}", border=True)
        if report.filler_hits:
            chips([f"{h.word} × {h.count}" for h in report.filler_hits], "orange")
        else:
            st.caption("No common filler words detected.")


def render_audience(
    result: dict,
    top_comments: list[str] | None,
    gap=None,
    include_competitors: bool = False,
    thumbnail_url: str = "",
    live: bool = True,
    uploaded_thumbnail: dict | None = None,
) -> None:
    sentiment = result.get("comment_sentiment", {})

    with st.container(border=True):
        st.markdown("##### :material/forum: What viewers said")
        if live and not top_comments:
            st.caption("No comments available for this video (comments may be disabled).")
        else:
            if live:
                st.caption(f"Based on the top {len(top_comments)} comments by relevance")
            if sentiment.get("summary"):
                st.write(sentiment["summary"])
            liked, complained = st.columns(2)
            with liked:
                st.markdown(":green-badge[:material/thumb_up: Viewers liked]")
                for theme in sentiment.get("positive_themes", []):
                    st.markdown(f"- {theme}")
                if not sentiment.get("positive_themes"):
                    st.caption("Nothing notable")
            with complained:
                st.markdown(":red-badge[:material/thumb_down: Viewers complained about]")
                for theme in sentiment.get("negative_themes", []):
                    st.markdown(f"- {theme}")
                if not sentiment.get("negative_themes"):
                    st.caption("Nothing notable")

    left, right = st.columns(2)

    with left:
        with st.container(border=True):
            st.markdown("##### :material/image_search: Thumbnail critique")
            if not live:
                st.caption("Re-run Analyze to critique the thumbnail.")
            elif not thumbnail_url and not uploaded_thumbnail:
                st.caption("No thumbnail yet — critique becomes available once you've uploaded one.")
            else:
                if thumbnail_url:
                    st.image(thumbnail_url, width=320)
                else:
                    st.image(uploaded_thumbnail["bytes"], width=320)
                review = st.session_state.get("thumbnail_review")
                if review is None:
                    st.caption("Costs one Gemini vision call — runs only when you ask for it.")
                    if st.button("Run thumbnail vision critique", icon=":material/visibility:", type="primary"):
                        with st.spinner("Analyzing thumbnail..."):
                            if thumbnail_url:
                                critique = critique_thumbnail(GEMINI_API_KEYS, thumbnail_url)
                            else:
                                critique = critique_thumbnail_bytes(
                                    GEMINI_API_KEYS, uploaded_thumbnail["bytes"], uploaded_thumbnail["mime_type"]
                                )
                            st.session_state["thumbnail_review"] = critique or {}
                        st.rerun()
                elif not review:
                    st.caption("Thumbnail review unavailable for this video.")
                else:
                    for label, ok in [
                        ("Legible at small size", review.get("legible_at_small_size")),
                        ("Clear focal point", review.get("has_clear_focal_point")),
                        ("Stands out in a busy feed", review.get("stands_out_in_feed")),
                    ]:
                        icon = ":material/check_circle:" if ok else ":material/cancel:"
                        color = "green" if ok else "red"
                        st.markdown(f":{color}[{icon}] {label}")
                    if review.get("feedback"):
                        st.write(review["feedback"])

    with right:
        with st.container(border=True):
            st.markdown("##### :material/swap_horiz: Audience gap")
            if not live:
                st.caption("Re-run Analyze to compare against competitors.")
            elif not include_competitors:
                st.caption('Enable "Compare against competitors" above and re-run to see this.')
            elif gap is None:
                st.caption("No competing videos found.")
            else:
                rivals = len(gap.top_competitors)
                if gap.gap > 0:
                    st.markdown(
                        f"Your top {rivals} competitors average "
                        f"**{gap.competitor_average_views:,} views**. That is an addressable "
                        f"gap of **~{gap.gap:,} viewers** you are not reaching."
                    )
                else:
                    st.markdown(
                        f"You are ahead of your top {rivals} competitors, who average "
                        f"**{gap.competitor_average_views:,} views**."
                    )

                if gap.missing_tags:
                    st.markdown(
                        f"**Add these {len(gap.missing_tags)} tags** — ranked by the views "
                        "sitting behind them, not how often they appear."
                    )
                    chips([f"{t} · {v:,} views" for t, v in gap.missing_tags], "orange")
                else:
                    st.caption("No keyword gaps — your tags already cover what competitors rank for.")

                for c in gap.top_competitors:
                    with st.expander(f"{c.view_count:,} views · {c.title}", icon=":material/play_circle:"):
                        st.caption(c.channel_title)
                        chips(c.tags[:15] if c.tags else [], "gray")


def render_repurpose(result: dict) -> None:
    scripts = result.get("shorts_scripts", [])
    posts = result.get("social_posts", {})

    with st.container(border=True):
        st.markdown("##### :material/smartphone: Short-form script concepts")
        if not scripts:
            st.caption("No short-form script concepts generated.")
        else:
            cols = st.columns(len(scripts))
            for col, (i, s) in zip(cols, enumerate(scripts, 1)):
                with col.container(border=True, height="stretch"):
                    st.markdown(f":violet-badge[Concept {i}]")
                    st.markdown(f"**{s.get('hook_line', '')}**")
                    st.text_area(
                        f"Script {i}", s.get("script", ""), height=220,
                        label_visibility="collapsed", key=f"shorts-script-{i}",
                    )
                    st.caption(s.get("caption", ""))
                    if s.get("rationale"):
                        st.caption(f":material/lightbulb: {s['rationale']}")

    with st.container(border=True):
        st.markdown("##### :material/share: Promo copy")
        x_tab, li_tab, yt_tab = st.tabs([
            ":material/tag: Twitter/X thread",
            ":material/work: LinkedIn",
            ":material/campaign: Community post",
        ])
        with x_tab:
            st.text_area("Twitter thread", posts.get("twitter_thread", ""), height=260, label_visibility="collapsed", key="social-twitter")
        with li_tab:
            st.text_area("LinkedIn post", posts.get("linkedin_post", ""), height=260, label_visibility="collapsed", key="social-linkedin")
        with yt_tab:
            st.text_area("Community post", posts.get("community_post", ""), height=160, label_visibility="collapsed", key="social-community")


def render_preproduction_checklist(checklist) -> None:
    with st.container(border=True):
        st.markdown("##### :material/checklist: Ready to record?")
        if checklist.ready_to_record:
            st.success("Nothing flagged — this looks ready to record.", icon=":material/check_circle:")
        else:
            st.warning("A few things worth fixing before you hit record.", icon=":material/warning:")
        for item in checklist.items:
            icon = {
                "ready": ":material/check_circle:", "needs_work": ":material/cancel:",
            }.get(item.status, ":material/help:")
            color = {"ready": "green", "needs_work": "red"}.get(item.status, "gray")
            st.markdown(f":{color}[{icon}] **{item.label}** — {item.detail}")


def render_actions(
    result: dict, video_id: str, title: str, playbook: list | None = None, live: bool = True,
    checklist=None,
) -> None:
    if checklist is not None:
        render_preproduction_checklist(checklist)

    with st.container(border=True):
        st.markdown("##### :material/rocket_launch: How to get more views")
        if not live:
            st.caption("Re-run Analyze for a fresh playbook — this needs live competitor, CTA, and thumbnail data that isn't stored with a saved analysis.")
        elif not playbook:
            st.success(
                "Nothing outstanding — metadata, calls to action, and shelf-life framing all "
                "check out. Growth from here is mostly about the content and thumbnail, "
                "not what this tool can measure.",
                icon=":material/check_circle:",
            )
        else:
            st.caption(f"{len(playbook)} concrete change{'s' if len(playbook) != 1 else ''}, ranked by how directly it ties to view count")
            for i, action in enumerate(playbook, 1):
                st.markdown(f"**{i}. {action.title}**")
                st.caption(action.detail)

    with st.container(border=True):
        st.markdown("##### :material/lightbulb: More ideas from Gemini")
        suggestions = result.get("suggestions", [])
        if not suggestions:
            st.caption("No suggestions generated.")
        for i, suggestion in enumerate(suggestions, 1):
            st.markdown(f"**{i}.** {suggestion}")

    with st.container(border=True):
        st.markdown("##### :material/download: Export this report")
        with st.container(horizontal=True):
            st.download_button(
                "JSON", build_json_export(title, result), icon=":material/data_object:",
                file_name=f"{video_id}-seo-report.json", mime="application/json",
            )
            st.download_button(
                "CSV", build_csv_export(title, result), icon=":material/table:",
                file_name=f"{video_id}-seo-report.csv", mime="text/csv",
            )
            st.download_button(
                "PDF", build_pdf_export(title, result), icon=":material/picture_as_pdf:",
                file_name=f"{video_id}-seo-report.pdf", mime="application/pdf",
            )


def render_report(
    video_id: str,
    title: str,
    channel: str,
    result: dict,
    *,
    original_description: str = "",
    existing_tags: list[str] | None = None,
    top_comments: list[str] | None = None,
    gap=None,
    include_competitors: bool = False,
    transcript_text: str | None = None,
    transcript_segments=None,
    thumbnail_url: str = "",
    live: bool = True,
    note: str = "",
    performance=None,
    projection=None,
    original_score: int = 0,
    optimized_score: int = 0,
    shelf=None,
    cta_report=None,
    revenue=None,
    playbook: list | None = None,
    planning: bool = False,
    uploaded_thumbnail: dict | None = None,
    speech_estimate=None,
    readability=None,
    variants: list | None = None,
    checklist=None,
) -> None:
    render_hero(video_id, title, channel, result, note, planning)

    metadata_tab, structure_tab, analysis_tab, audience_tab, repurpose_tab, actions_tab = st.tabs([
        ":material/sell: Metadata",
        ":material/segment: Structure",
        ":material/query_stats: Analysis",
        ":material/groups: Audience",
        ":material/rocket_launch: Repurpose",
        ":material/checklist: Actions",
    ])

    with metadata_tab:
        if planning and variants and len(variants) > 1:
            render_variant_comparison(variants)
        render_metadata(result, existing_tags or [])
    with structure_tab:
        render_structure(result, cta_report, live, speech_estimate)
    with analysis_tab:
        render_analysis(
            result, original_description, existing_tags,
            transcript_text, transcript_segments, live,
            performance, projection, original_score, optimized_score, shelf, revenue, readability,
        )
    with audience_tab:
        render_audience(result, top_comments, gap, include_competitors, thumbnail_url, live, uploaded_thumbnail)
    with repurpose_tab:
        render_repurpose(result)
    with actions_tab:
        render_actions(result, video_id, title, playbook, live, checklist)


# ---------------------------------------------------------------- app

conn = _db_connection()
if conn is not None and not ensure_schema(conn):
    # Cached connection has gone stale (e.g. a serverless provider dropped it
    # after idle suspend). Drop it from the cache and reconnect fresh rather
    # than serving broken queries against a dead connection for the rest of
    # this process's life.
    _db_connection.clear()
    conn = _db_connection()
    if conn is not None:
        ensure_schema(conn)

def render_masthead() -> None:
    st.title("YouTube SEO Studio", text_alignment="center")
    st.caption(
        f"{date.today():%A, %d %B %Y}  ·  THE DESK FOR CREATORS  ·  NO. {date.today():%j}",
        text_alignment="center",
    )


# The name is the only credential: it scopes saved history so two people using
# the same deployment never see each other's analyses. Nothing proceeds without it.
if not st.session_state.get("user_name"):
    render_masthead()
    st.divider()
    st.space("large")

    _, middle, _ = st.columns([1, 1.4, 1])
    with middle:
        with st.container(border=True):
            st.markdown("#### Who's writing today?")
            st.caption("Your name keeps your saved analyses separate from everyone else's. That's all it's used for.")
            with st.form("sign_in", border=False):
                entered = st.text_input(
                    "Your name", placeholder="e.g. Abhishek",
                    label_visibility="collapsed", icon=":material/person:",
                )
                if st.form_submit_button("Start writing", icon=":material/arrow_forward:", type="primary", width="stretch"):
                    if entered.strip():
                        st.session_state["user_name"] = entered.strip()
                        st.rerun()
                    else:
                        st.warning("Enter a name to continue.", icon=":material/edit:")
    st.stop()

user_name = st.session_state["user_name"]

menu_col, account_col = st.columns([1, 1], vertical_alignment="center")

with menu_col:
    with st.popover(":material/menu:", help="History"):
        st.markdown("##### :material/history: Your history")
        if conn is None:
            st.caption("Database not connected — history unavailable this session.")
        else:
            history_search = st.text_input(
                "Search history", key="history_search", placeholder="Search title or channel",
                label_visibility="collapsed", icon=":material/search:",
            ).strip()
            recent = list_recent(conn, user_name, search=history_search)
            if not recent:
                st.caption("No matching analyses." if history_search else "No saved analyses yet.")
            for row in recent:
                label = row["title"][:44] + ("…" if len(row["title"]) > 44 else "")
                if st.button(label, key=f"hist-{row['id']}", width="stretch"):
                    st.session_state["load_row"] = row
                    st.rerun()

with account_col:
    with st.container(horizontal=True, horizontal_alignment="right"):
        with st.popover(user_name, icon=":material/account_circle:"):
            st.caption(f"Signed in as **{user_name}**")
            if st.button("Switch name", icon=":material/logout:", width="stretch"):
                for key in ("user_name", "load_row", "current_analysis", "thumbnail_review"):
                    st.session_state.pop(key, None)
                st.rerun()

render_masthead()
st.divider()

mode = st.segmented_control(
    "Mode", ["Analyze existing video", "Plan a new video"],
    default="Analyze existing video", label_visibility="collapsed", key="mode",
)

run = False
run_plan = False

if mode == "Plan a new video":
    st.caption("No video needed yet — draft a title, description, and script, and get the same SEO guidance.")
    with st.form("plan", border=False):
        plan_title = st.text_input(
            "Working title", placeholder="Working title for the video",
            icon=":material/title:",
        )
        plan_description = st.text_area(
            "Draft description (optional)", placeholder="Draft description, if you have one...",
            height=100,
        )
        plan_tags = st.text_input(
            "Draft tags (optional, comma-separated)", placeholder="tag one, tag two, tag three",
            icon=":material/sell:",
        )
        plan_script = st.text_area(
            "Draft script or transcript (optional)", placeholder="Paste your script or talking points...",
            height=160,
            help="Used for hook analysis and keyword density. Chapters are never generated here, since there's no real video duration to base timestamps on.",
        )
        plan_title_variants = st.text_area(
            "Additional title variants (optional, up to 2, one per line)",
            placeholder="Alternate title 1\nAlternate title 2",
            height=70,
            help="Each variant runs its own full Gemini analysis to compare — up to 2x-3x the usual request cost.",
        )
        plan_thumbnail = st.file_uploader(
            "Thumbnail concept (optional)", type=["png", "jpg", "jpeg", "webp"],
        )
        run_plan = st.form_submit_button(
            "Plan this video", icon=":material/auto_awesome:", type="primary", width="stretch",
        )
        include_competitors = st.checkbox(
            "Compare against competitors",
            help="Uses 100x more YouTube API quota than a routine analysis. Off by default.",
            key="plan-competitors",
        )
else:
    with st.form("analyze", border=False):
        url_col, button_col = st.columns([4, 1], vertical_alignment="bottom")
        url = url_col.text_input(
            "YouTube video URL", placeholder="https://www.youtube.com/watch?v=...",
            label_visibility="collapsed", icon=":material/link:",
        )
        run = button_col.form_submit_button(
            "Analyze", icon=":material/auto_awesome:", type="primary", width="stretch",
        )
        include_competitors = st.checkbox(
            "Compare against competitors",
            help="Uses 100x more YouTube API quota than a routine analysis. Off by default.",
            key="analyze-competitors",
        )

if run_plan:
    st.session_state.pop("load_row", None)

    if not GEMINI_API_KEY:
        st.error("Missing GEMINI_API_KEY. Add it to your .env file.", icon=":material/key_off:")
        st.stop()

    if not plan_title.strip():
        st.warning("Enter a working title first.", icon=":material/edit_off:")
        st.stop()

    plan_tags_list = [t.strip() for t in plan_tags.split(",") if t.strip()]

    with st.status("Planning video...", expanded=True) as status:
        meta = build_planned_meta(
            plan_title.strip(), plan_description.strip(), plan_tags_list,
            channel_title=f"{user_name} (planned)",
        )

        competitors = []
        if include_competitors and YOUTUBE_API_KEY:
            st.write(":material/groups: Finding competing videos")
            competitors = find_competitors(meta.title, YOUTUBE_API_KEY, exclude_video_id="")

        st.write(":material/auto_awesome: Generating SEO suggestions with Gemini")
        try:
            result = generate_seo(
                api_keys=GEMINI_API_KEYS,
                title=meta.title,
                description=meta.description,
                existing_tags=meta.tags,
                transcript=plan_script.strip() or None,
                comments=[],
                suppress_chapters=True,
            )
        except Exception as exc:
            status.update(label="Gemini request failed", state="error")
            st.error(f"LLM request failed: {exc}", icon=":material/error:")
            st.stop()

        # No cache lookup here, unlike the existing-video path: a draft has no
        # stable identity to cache against (the title/script may get edited
        # between runs), so this always calls Gemini fresh.
        if conn is not None:
            try:
                save_analysis(conn, user_name, meta.video_id, meta.title, meta.channel_title, result)
            except Exception:
                pass  # history is best-effort, never block the page over it

        # Each variant is a full, independent generate_seo() call (own tags,
        # description, hook) -- not a free structural comparison -- capped at
        # 2 so one planning session can't burn more than 3x the usual request
        # cost. The primary result above stays the one driving every other
        # tab; variants exist only for the comparison view.
        variant_titles = [t.strip() for t in plan_title_variants.splitlines() if t.strip()][:2]
        variants = [(meta.title, result)]
        for variant_title in variant_titles:
            st.write(f":material/auto_awesome: Generating variant: {variant_title}")
            try:
                variant_result = generate_seo(
                    api_keys=GEMINI_API_KEYS,
                    title=variant_title,
                    description=meta.description,
                    existing_tags=meta.tags,
                    transcript=plan_script.strip() or None,
                    comments=[],
                    suppress_chapters=True,
                )
            except Exception:
                continue  # one variant failing is not worth aborting the whole plan
            variants.append((variant_title, variant_result))

        status.update(label="Plan complete", state="complete", expanded=False)

    st.session_state["current_analysis"] = {
        "meta": meta, "result": result, "top_comments": [],
        "competitors": competitors, "include_competitors": include_competitors,
        "transcript_segments": None, "transcript_text": plan_script.strip() or None,
        "note": "", "planning": True, "variants": variants,
        "thumbnail_upload": (
            {"bytes": plan_thumbnail.getvalue(), "mime_type": plan_thumbnail.type}
            if plan_thumbnail is not None else None
        ),
    }
    st.session_state.pop("thumbnail_review", None)

if run:
    st.session_state.pop("load_row", None)

    if not YOUTUBE_API_KEY or not GEMINI_API_KEY:
        st.error("Missing YOUTUBE_API_KEY or GEMINI_API_KEY. Add them to your .env file.", icon=":material/key_off:")
        st.stop()

    if not url:
        st.warning("Enter a URL first.", icon=":material/link_off:")
        st.stop()

    try:
        video_id = parse_video_id(url)
    except InvalidURLError as exc:
        st.error(str(exc), icon=":material/error:")
        st.stop()

    with st.status("Analyzing video...", expanded=True) as status:
        st.write(":material/download: Fetching video metadata")
        try:
            meta = fetch_metadata(video_id, YOUTUBE_API_KEY)
        except VideoNotFoundError as exc:
            status.update(label="Video not found", state="error")
            st.error(str(exc), icon=":material/error:")
            st.stop()
        except Exception as exc:
            status.update(label="Metadata fetch failed", state="error")
            st.error(f"Failed to fetch video metadata: {exc}", icon=":material/error:")
            st.stop()

        st.write(":material/subtitles: Fetching transcript")
        transcript_segments = fetch_transcript_segments(video_id)
        transcript = segments_to_text(transcript_segments) if transcript_segments else None
        if not transcript:
            st.write(":material/warning: No transcript — chapters, hook, keywords, and pacing will be limited")

        st.write(":material/forum: Fetching comments")
        top_comments = fetch_top_comments(video_id, YOUTUBE_API_KEY)

        competitors = []
        if include_competitors:
            st.write(":material/groups: Finding competing videos")
            competitors = find_competitors(meta.title, YOUTUBE_API_KEY, exclude_video_id=video_id)

        cached_result = get_cached_analysis(conn, user_name, video_id) if conn is not None else None
        if cached_result is not None:
            result = cached_result
            st.write(":material/bolt: Found a saved analysis — skipping Gemini entirely")
            note = "Loaded from a previous analysis of this video — 0 Gemini calls spent."
        else:
            st.write(":material/auto_awesome: Generating SEO suggestions with Gemini")
            note = ""
            try:
                result = generate_seo(
                    api_keys=GEMINI_API_KEYS,
                    title=meta.title,
                    description=meta.description,
                    existing_tags=meta.tags,
                    transcript=transcript,
                    comments=top_comments,
                )
            except Exception as exc:
                status.update(label="Gemini request failed", state="error")
                st.error(f"LLM request failed: {exc}", icon=":material/error:")
                st.stop()

            if conn is not None:
                try:
                    save_analysis(conn, user_name, video_id, meta.title, meta.channel_title, result)
                except Exception:
                    pass  # history is best-effort, never block the page over it

        status.update(label="Analysis complete", state="complete", expanded=False)

    # Persisted rather than rendered inline: the on-demand thumbnail button
    # triggers its own script rerun, which would otherwise wipe out everything
    # computed in this block before it gets a chance to render.
    st.session_state["current_analysis"] = {
        "meta": meta, "result": result, "top_comments": top_comments,
        "competitors": competitors, "include_competitors": include_competitors,
        "transcript_segments": transcript_segments, "transcript_text": transcript,
        "note": note,
    }
    st.session_state.pop("thumbnail_review", None)

if st.session_state.get("load_row"):
    row = st.session_state["load_row"]
    result = get_analysis(conn, user_name, row["id"]) if conn is not None else None

    if result is None:
        st.warning("Saved analysis not found — it may have been deleted.", icon=":material/search_off:")
    else:
        render_report(
            row["video_id"], row["title"], row["channel"], result,
            live=False,
            note=f"Saved {row['analyzed_at']:%d %b %Y, %H:%M} · no API quota spent",
            planning=row["video_id"].startswith("planned-"),
        )

elif st.session_state.get("current_analysis"):
    data = st.session_state["current_analysis"]
    meta = data["meta"]
    result = data["result"]
    planning = data.get("planning", False)

    # Both sides are scored by the same rules, so the delta reflects the
    # metadata improvement alone. A published video keeps its hashtags in the
    # description, so they are pulled out to match the generated hashtag field.
    original_score, _ = compute_health_score(
        meta.title, meta.description, meta.tags, extract_hashtags(meta.description)
    )
    titles = result.get("titles", [])
    optimized_score, optimized_rules = compute_health_score(
        titles[0] if titles else meta.title,
        result.get("description", ""),
        result.get("tags", []),
        result.get("hashtags", []),
    )
    # Measured against the tags the creator would actually publish -- the
    # generated set plus what they already had -- so the gap is not inflated by
    # tags this run is already recommending.
    gap = audience_gap(
        meta.view_count,
        list(meta.tags) + result.get("tags", []),
        data["competitors"],
    )
    shelf = classify(meta.title, meta.tags, data["transcript_text"])
    cta_report = analyze_ctas(data["transcript_segments"])
    speech_estimate = estimate_spoken_length(data["transcript_text"])
    readability = scan_readability(data["transcript_text"])

    # A planned video has no real views, publish date, or category yet -- a
    # projection or revenue estimate off all-zero inputs would be a meaningless
    # "$0" box, not a forecast, so these are simply never computed for one.
    performance = projection = revenue = None
    if not planning:
        performance = summarize_performance(
            meta.view_count, meta.like_count, meta.comment_count, meta.published_at
        )
        projection = project_views(
            meta.view_count, performance.views_per_day, optimized_score - original_score
        )
        # Revenue rides on the projected extra views, not the whole projection --
        # the baseline views would have arrived with or without the SEO changes.
        revenue = estimate_revenue(
            meta.view_count,
            meta.category_id,
            projection.low_views - projection.baseline_views,
            projection.high_views - projection.baseline_views,
        )

    playbook = build_playbook(
        optimized_rules, gap, cta_report, shelf, st.session_state.get("thumbnail_review")
    )
    # A pre-record readiness check only makes sense before there's anything to
    # measure -- once real performance data exists (a live, already-uploaded
    # video), the growth playbook above already covers "what to fix."
    checklist = None
    if planning:
        checklist = build_preproduction_checklist(
            optimized_score, result.get("hook_analysis", {}), speech_estimate, shelf
        )

    render_report(
        meta.video_id, meta.title, meta.channel_title, result,
        original_description=meta.description,
        existing_tags=meta.tags,
        top_comments=data["top_comments"],
        gap=gap,
        include_competitors=data["include_competitors"],
        transcript_text=data["transcript_text"],
        transcript_segments=data["transcript_segments"],
        thumbnail_url=meta.thumbnail_url,
        live=True,
        note=data.get("note", ""),
        performance=performance,
        projection=projection,
        original_score=original_score,
        optimized_score=optimized_score,
        shelf=shelf,
        cta_report=cta_report,
        revenue=revenue,
        playbook=playbook,
        planning=planning,
        uploaded_thumbnail=data.get("thumbnail_upload"),
        speech_estimate=speech_estimate,
        readability=readability,
        variants=data.get("variants"),
        checklist=checklist,
    )

else:
    st.space("medium")
    st.markdown("## One link in. A full workup out.", text_alignment="center")
    st.markdown(
        "Everything below is read from the video's public data and a single model call — "
        "no upload, no channel access, nothing to connect.",
        text_alignment="center",
    )
    st.space("medium")

    desks = [
        (
            "THE METADATA DESK",
            [
                ("Thirty-five tags, at minimum", "ranked for this exact video, with the ones you already use kept and marked as such."),
                ("Five alternative titles", "each measured against the hundred-character cutoff before you ever paste it."),
                ("A description and hashtags", "chapter timestamps folded in, closing on a call to action."),
            ],
        ),
        (
            "THE READING ROOM",
            [
                ("Chapters from real topic shifts", "pulled off the transcript, never evenly spaced filler."),
                ("A verdict on your first thirty seconds", "whether the hook lands, and a rewrite if it doesn't."),
                ("Keyword density and speech pacing", "the phrases you actually repeat, and where you race or stall."),
            ],
        ),
        (
            "THE BACK PAGE",
            [
                ("What the comments say", "praise and complaints separated into themes, not a star rating."),
                ("The keyword gap", "tags your competitors agree on that you skipped entirely."),
                ("Copy for everywhere else", "three short-form scripts, a thread, a post — and the whole report as PDF."),
            ],
        ),
    ]

    for column, (desk, items) in zip(st.columns(3, gap="large"), desks):
        with column:
            st.markdown(f"###### {desk}")
            st.divider()
            for lead, body in items:
                st.markdown(f"**{lead}** — {body}")
