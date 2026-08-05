import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from comments import fetch_top_comments
from competitors import find_competitors, tag_gap
from db import ensure_schema, get_analysis, get_cached_analysis, get_connection, list_recent, save_analysis
from export import build_csv_export, build_json_export, build_pdf_export
from keywords import top_ngrams
from limits import check_limits, compute_health_score
from llm import generate_seo
from pacing import SILENT_GAP_THRESHOLD_SECONDS, find_silent_gaps, words_per_minute_blocks
from seo_diff import diff_description, diff_tags
from thumbnail import critique_thumbnail
from transcript import fetch_transcript_segments, segments_to_text
from youtube import InvalidURLError, VideoNotFoundError, fetch_metadata, parse_video_id

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


def render_hero(video_id: str, title: str, channel: str, result: dict, note: str = "") -> None:
    score, rules = compute_health_score(
        title, result.get("description", ""), result.get("tags", []), result.get("hashtags", [])
    )
    passed = sum(r.passed for r in rules)

    with st.container(border=True):
        art, info = st.columns([1, 3], vertical_alignment="center")
        art.image(thumbnail_for(video_id), width="stretch")
        with info:
            st.markdown(f"### {title}")
            st.caption(f":material/account_circle: {channel}" if channel else "")
            score_color = "green" if score >= 80 else "orange" if score >= 55 else "red"
            st.markdown(
                f":{score_color}-badge[:material/health_metrics: Health {score}%] "
                f":violet-badge[:material/sell: {len(result.get('tags', []))} tags] "
                f":blue-badge[:material/tag: {len(result.get('hashtags', []))} hashtags] "
                f":gray-badge[:material/segment: {len(result.get('chapters', []))} chapters]"
            )
            if note:
                st.caption(note)

    with st.container(horizontal=True):
        st.metric(
            "Metadata health", f"{score}%", delta=f"{passed}/{len(rules)} checks",
            delta_color="off", border=True,
            help="Compliance against YouTube best practices, not just hard limits.",
        )
        for check in check_limits(
            title, result.get("description", ""), result.get("tags", []), result.get("hashtags", [])
        ):
            st.metric(
                check.label, f"{check.current:,}",
                delta=f"limit {check.maximum:,}",
                delta_color="off" if check.ok else "inverse",
                border=True,
            )

    with st.expander("Compliance checklist", icon=":material/checklist:"):
        for r in rules:
            icon = ":material/check_circle:" if r.passed else ":material/cancel:"
            color = "green" if r.passed else "red"
            st.markdown(f":{color}[{icon}] **{r.label}** — {r.detail}")


# ---------------------------------------------------------------- sections


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

        with st.container(border=True):
            st.markdown("##### :material/tag: Hashtags")
            st.caption(f"{len(hashtags)}/15 hashtags")
            chips(hashtags, "blue")
            st.code(" ".join(hashtags), language=None, wrap_lines=True)


def render_structure(result: dict) -> None:
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


def render_analysis(
    result: dict,
    original_description: str = "",
    existing_tags: list[str] | None = None,
    transcript_text: str | None = None,
    transcript_segments=None,
    live: bool = True,
) -> None:
    if not live:
        st.caption(
            "Keyword density, pacing, and the SEO diff are computed from live video data, "
            "which is not stored with a saved analysis. Re-run Analyze to see them."
        )

    with st.container(border=True):
        st.markdown("##### :material/difference: Before vs. after")
        if not live:
            st.caption("Unavailable for a saved analysis.")
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


def render_audience(
    result: dict,
    top_comments: list[str] | None,
    competitors: list | None,
    include_competitors: bool,
    thumbnail_url: str = "",
    live: bool = True,
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
            else:
                if thumbnail_url:
                    st.image(thumbnail_url, width=320)
                review = st.session_state.get("thumbnail_review")
                if review is None:
                    st.caption("Costs one Gemini vision call — runs only when you ask for it.")
                    if st.button("Run thumbnail vision critique", icon=":material/visibility:", type="primary"):
                        with st.spinner("Analyzing thumbnail..."):
                            st.session_state["thumbnail_review"] = critique_thumbnail(GEMINI_API_KEYS, thumbnail_url) or {}
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
            st.markdown("##### :material/groups: Competitors")
            if not live:
                st.caption("Re-run Analyze to compare against competitors.")
            elif not include_competitors:
                st.caption('Enable "Compare against competitors" above and re-run to see this.')
            elif not competitors:
                st.caption("No competing videos found.")
            else:
                gaps = tag_gap(result.get("tags", []), competitors)
                if gaps:
                    st.markdown("**Keyword gap** — tags competitors use that you don't")
                    chips([f"{t} ({n})" for t, n in gaps], "orange")
                else:
                    st.caption("No keyword gaps — your tags already cover what competitors use.")

                for c in competitors:
                    with st.expander(c.title, icon=":material/play_circle:"):
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


def render_actions(result: dict, video_id: str, title: str) -> None:
    with st.container(border=True):
        st.markdown("##### :material/lightbulb: Suggestions to grow this video")
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
    competitors: list | None = None,
    include_competitors: bool = False,
    transcript_text: str | None = None,
    transcript_segments=None,
    thumbnail_url: str = "",
    live: bool = True,
    note: str = "",
) -> None:
    render_hero(video_id, title, channel, result, note)

    metadata_tab, structure_tab, analysis_tab, audience_tab, repurpose_tab, actions_tab = st.tabs([
        ":material/sell: Metadata",
        ":material/segment: Structure",
        ":material/query_stats: Analysis",
        ":material/groups: Audience",
        ":material/rocket_launch: Repurpose",
        ":material/checklist: Actions",
    ])

    with metadata_tab:
        render_metadata(result, existing_tags or [])
    with structure_tab:
        render_structure(result)
    with analysis_tab:
        render_analysis(
            result, original_description, existing_tags,
            transcript_text, transcript_segments, live,
        )
    with audience_tab:
        render_audience(result, top_comments, competitors, include_competitors, thumbnail_url, live)
    with repurpose_tab:
        render_repurpose(result)
    with actions_tab:
        render_actions(result, video_id, title)


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

with st.sidebar:
    st.markdown("### :material/movie_filter: SEO Studio")

    user_name = st.text_input(
        "Your name", key="user_name", placeholder="Your name",
        label_visibility="collapsed",
        help="Separates your saved history from everyone else's using this app.",
    ).strip()

    st.markdown("##### :material/history: History")
    if conn is None:
        st.caption("Database not connected — history unavailable this session.")
    elif not user_name:
        st.caption("Enter your name above to see your saved analyses.")
    else:
        history_search = st.text_input(
            "Search history", key="history_search", placeholder="Search title or channel",
            label_visibility="collapsed", icon=":material/search:",
        ).strip()
        recent = list_recent(conn, user_name, search=history_search)
        if not recent:
            st.caption("No matching analyses." if history_search else "No saved analyses yet.")
        for row in recent:
            label = row["title"][:38] + ("…" if len(row["title"]) > 38 else "")
            if st.button(label, key=f"hist-{row['id']}", width="stretch"):
                st.session_state["load_row"] = row
                st.rerun()

    st.caption("Gemini free tier is 20 requests/day per key. One analysis = 1 call, +1 if you run the thumbnail critique.")

st.title(":material/movie_filter: YouTube SEO Studio")
st.caption("Paste a video URL — get tags, titles, chapters, repurposed copy, and an audience read in one pass.")

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
    )

if run:
    st.session_state.pop("load_row", None)

    if not YOUTUBE_API_KEY or not GEMINI_API_KEY:
        st.error("Missing YOUTUBE_API_KEY or GEMINI_API_KEY. Add them to your .env file.", icon=":material/key_off:")
        st.stop()

    if conn is not None and not user_name:
        st.warning("Enter your name in the sidebar first, so your history stays separate from other users'.", icon=":material/badge:")
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
        )

elif st.session_state.get("current_analysis"):
    data = st.session_state["current_analysis"]
    meta = data["meta"]
    render_report(
        meta.video_id, meta.title, meta.channel_title, data["result"],
        original_description=meta.description,
        existing_tags=meta.tags,
        top_comments=data["top_comments"],
        competitors=data["competitors"],
        include_competitors=data["include_competitors"],
        transcript_text=data["transcript_text"],
        transcript_segments=data["transcript_segments"],
        thumbnail_url=meta.thumbnail_url,
        live=True,
        note=data.get("note", ""),
    )

else:
    st.space("medium")
    cols = st.columns(3)
    features = [
        (":material/sell:", "Metadata", "35+ SEO tags, 5 title options, an optimized description, and hashtags."),
        (":material/segment:", "Structure", "Chapter timestamps from real topic shifts, plus a hook verdict on your first 30 seconds."),
        (":material/query_stats:", "Analysis", "Keyword density, speech pacing, silent gaps, and a before/after SEO diff."),
        (":material/groups:", "Audience", "What viewers praised and complained about, competitor keyword gaps, thumbnail critique."),
        (":material/rocket_launch:", "Repurpose", "Three short-form script concepts and ready-to-post promo copy."),
        (":material/checklist:", "Actions", "A metadata health score, growth suggestions, and JSON/CSV/PDF export."),
    ]
    for col, (icon, heading, body) in zip(cols * 2, features):
        with col.container(border=True, height="stretch"):
            st.markdown(f"##### {icon} {heading}")
            st.caption(body)
