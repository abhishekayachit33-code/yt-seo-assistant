import html
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

st.set_page_config(page_title="YouTube SEO Assistant", layout="centered")

st.markdown(
    """
    <style>
    .stApp { background-color: #FFFFFF; }
    h1, h2, h3 { color: #1A1A1A; }
    .stButton > button {
        background-color: #1A73E8;
        color: #FFFFFF;
        border: none;
        border-radius: 6px;
        font-weight: 600;
    }
    .stButton > button:hover {
        background-color: #1558B0;
        color: #FFFFFF;
    }
    div[data-testid="stTabs"] button[aria-selected="true"] {
        color: #1A73E8 !important;
    }
    div[data-testid="stTabs"] [data-baseweb="tab-highlight"] {
        background-color: #1A73E8 !important;
    }
    /* Long comma-joined lists must wrap, or only the first few items are visible. */
    div[data-testid="stCode"] pre, div[data-testid="stCode"] code {
        white-space: pre-wrap !important;
        word-break: break-word !important;
    }
    .tag-chips {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        margin: 4px 0 16px 0;
    }
    .tag-chips span {
        background-color: #EAF1FB;
        color: #14418B;
        border: 1px solid #C7DAF7;
        border-radius: 12px;
        padding: 2px 10px;
        font-size: 0.82rem;
        line-height: 1.6;
    }
    .tag-chips span.existing {
        background-color: #F3F4F6;
        color: #4B5563;
        border-color: #E5E7EB;
    }
    .tag-chips span.existing::after {
        content: " · kept";
        font-size: 0.72rem;
        color: #9CA3AF;
    }
    .chapter-row {
        display: flex;
        gap: 12px;
        padding: 5px 0;
        border-bottom: 1px solid #EEF1F5;
    }
    .chapter-row .ts {
        font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
        color: #1A73E8;
        font-weight: 600;
        min-width: 56px;
    }
    .limit-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 8px;
        margin: 8px 0 20px 0;
    }
    .limit-card {
        border: 1px solid #E5E7EB;
        border-radius: 8px;
        padding: 8px 12px;
    }
    .limit-card .label {
        font-size: 0.78rem;
        color: #6B7280;
    }
    .limit-card .value {
        font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
        font-size: 0.95rem;
        font-weight: 600;
    }
    .limit-card.ok { border-left: 3px solid #1A9E5C; }
    .limit-card.ok .value { color: #1A9E5C; }
    .limit-card.fail { border-left: 3px solid #C0362C; }
    .limit-card.fail .value { color: #C0362C; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def _db_connection():
    return get_connection()


def render_limit_checks(title: str, description: str, tags: list[str], hashtags: list[str]) -> None:
    checks = check_limits(title, description, tags, hashtags)
    cards = "".join(
        f'<div class="limit-card {"ok" if c.ok else "fail"}">'
        f'<div class="label">{html.escape(c.label)}</div>'
        f'<div class="value">{c.current}/{c.maximum}</div>'
        f"</div>"
        for c in checks
    )
    st.markdown(f'<div class="limit-grid">{cards}</div>', unsafe_allow_html=True)
    if any(not c.ok for c in checks):
        st.warning("One or more fields exceed YouTube's limits — trim before publishing.")


def render_health_score(title: str, description: str, tags: list[str], hashtags: list[str]) -> None:
    score, rules = compute_health_score(title, description, tags, hashtags)
    st.metric("Metadata Health Score", f"{score}%")
    with st.expander("Compliance checklist"):
        for r in rules:
            st.markdown(f"{'PASS' if r.passed else 'FAIL'} — **{r.label}** ({r.detail})")


def render_export_buttons(video_id: str, title: str, result: dict) -> None:
    col1, col2, col3 = st.columns(3)
    with col1:
        st.download_button(
            "Download JSON", build_json_export(title, result),
            file_name=f"{video_id}-seo-report.json", mime="application/json",
            use_container_width=True,
        )
    with col2:
        st.download_button(
            "Download CSV", build_csv_export(title, result),
            file_name=f"{video_id}-seo-report.csv", mime="text/csv",
            use_container_width=True,
        )
    with col3:
        st.download_button(
            "Download PDF", build_pdf_export(title, result),
            file_name=f"{video_id}-seo-report.pdf", mime="application/pdf",
            use_container_width=True,
        )


def render_shorts_scripts(result: dict) -> None:
    scripts = result.get("shorts_scripts", [])
    if not scripts:
        st.info("No short-form script concepts generated.")
        return
    for i, s in enumerate(scripts, 1):
        st.markdown(f"**Concept {i}: {s.get('hook_line', '')}**")
        st.text_area(
            f"Script {i}", s.get("script", ""), height=150,
            label_visibility="collapsed", key=f"shorts-script-{i}",
        )
        st.caption(s.get("caption", ""))
        st.divider()


def render_social_posts(result: dict) -> None:
    posts = result.get("social_posts", {})
    st.markdown("**Twitter/X thread**")
    st.text_area("Twitter thread", posts.get("twitter_thread", ""), height=150, label_visibility="collapsed", key="social-twitter")
    st.markdown("**LinkedIn post**")
    st.text_area("LinkedIn post", posts.get("linkedin_post", ""), height=150, label_visibility="collapsed", key="social-linkedin")
    st.markdown("**YouTube Community post**")
    st.text_area("Community post", posts.get("community_post", ""), height=100, label_visibility="collapsed", key="social-community")


def render_comment_sentiment(sentiment: dict) -> None:
    if sentiment and sentiment.get("summary"):
        st.write(sentiment["summary"])
    positive = (sentiment or {}).get("positive_themes", [])
    negative = (sentiment or {}).get("negative_themes", [])
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Viewers liked**")
        for theme in positive:
            st.markdown(f"- {theme}")
        if not positive:
            st.caption("Nothing notable")
    with col2:
        st.markdown("**Viewers complained about**")
        for theme in negative:
            st.markdown(f"- {theme}")
        if not negative:
            st.caption("Nothing notable")


def render_core_tabs(tabs: dict, existing_tags: list[str], result: dict) -> None:
    """Renders the seven tabs that come straight from generate_seo()'s stored
    result -- shared between a fresh run and a reloaded history entry, since
    a saved analysis only has this data, not comments/competitors/thumbnail."""
    tags = result.get("tags", [])
    titles = result.get("titles", [])
    description = result.get("description", "")
    hashtags = result.get("hashtags", [])
    chapters = result.get("chapters", [])
    suggestions = result.get("suggestions", [])
    hook = result.get("hook_analysis", {})

    with tabs["tags"]:
        joined = ", ".join(tags)
        st.caption(f"{len(tags)} tags · {len(joined)}/500 characters")

        existing_lower = {t.lower() for t in existing_tags}
        chips = "".join(
            f'<span class="{"existing" if t.lower() in existing_lower else ""}">{html.escape(t)}</span>'
            for t in tags
        )
        st.markdown(f'<div class="tag-chips">{chips}</div>', unsafe_allow_html=True)
        if existing_tags:
            kept = len(existing_lower & {t.lower() for t in tags})
            st.caption(f"{kept} of your existing {len(existing_tags)} tags were kept; the rest are new suggestions.")

        st.caption("Copy for the tags field")
        st.code(joined, language=None)

    with tabs["titles"]:
        if titles:
            for i, t in enumerate(titles, 1):
                st.markdown(
                    f"**{i}.** {t}  \n<span style='color:#9CA3AF;font-size:0.78rem'>{len(t)}/100 characters</span>",
                    unsafe_allow_html=True,
                )
        else:
            st.info("No title suggestions generated.")

    with tabs["description"]:
        if description:
            st.text_area("Optimized description", description, height=280, label_visibility="collapsed")
        else:
            st.info("No description generated.")

    with tabs["hashtags"]:
        st.caption(f"{len(hashtags)}/15 hashtags")
        chips = "".join(f"<span>{html.escape(h)}</span>" for h in hashtags)
        st.markdown(f'<div class="tag-chips">{chips}</div>', unsafe_allow_html=True)
        st.code(" ".join(hashtags), language=None)

    with tabs["chapters"]:
        if chapters:
            rows = "".join(
                f'<div class="chapter-row"><span class="ts">{html.escape(str(c.get("timestamp", "")))}</span>'
                f'<span>{html.escape(str(c.get("title", "")))}</span></div>'
                for c in chapters
            )
            st.markdown(rows, unsafe_allow_html=True)
            st.caption("Copy into your video description")
            st.code(
                "\n".join(f"{c.get('timestamp', '')} {c.get('title', '')}" for c in chapters),
                language=None,
            )
        else:
            st.info("No chapters generated (transcript was not available).")

    with tabs["hook"]:
        verdict = hook.get("verdict", "")
        if verdict and verdict != "unavailable":
            st.markdown(f"**Verdict:** {verdict}")
            if hook.get("reasoning"):
                st.write(hook["reasoning"])
            if hook.get("rewrite"):
                st.caption("Suggested rewrite for the opening")
                st.info(hook["rewrite"])
        else:
            st.info("Hook analysis needs a transcript, which was not available for this video.")

    with tabs["suggestions"]:
        for i, suggestion in enumerate(suggestions, 1):
            st.markdown(f"**{i}.** {suggestion}")


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
    st.subheader("Your name")
    user_name = st.text_input(
        "Your name", key="user_name", placeholder="e.g. Abhishek",
        label_visibility="collapsed",
        help="Separates your saved history from everyone else's using this app.",
    ).strip()

    st.subheader("History")
    if conn is None:
        st.caption("Database not connected — history unavailable this session.")
    elif not user_name:
        st.caption("Enter your name above to see your saved analyses.")
    else:
        history_search = st.text_input(
            "Search history", key="history_search", placeholder="Search by title or channel...",
            label_visibility="collapsed",
        ).strip()
        recent = list_recent(conn, user_name, search=history_search)
        if not recent:
            st.caption("No matching analyses." if history_search else "No saved analyses yet.")
        for row in recent:
            label = row["title"][:40] + ("…" if len(row["title"]) > 40 else "")
            if st.button(label, key=f"hist-{row['id']}", use_container_width=True):
                st.session_state["load_row"] = row
                st.rerun()

st.title("YouTube SEO Assistant")
st.caption("Paste a video URL to generate SEO tags, titles, descriptions, chapters, and reach suggestions.")

url = st.text_input("YouTube video URL", placeholder="https://www.youtube.com/watch?v=...")
include_competitors = st.checkbox(
    "Include competitor comparison",
    help="Uses 100x more YouTube API quota than a routine analysis. Off by default.",
)
run = st.button("Analyze")

if run:
    st.session_state.pop("load_row", None)

    if not YOUTUBE_API_KEY or not GEMINI_API_KEY:
        st.error("Missing YOUTUBE_API_KEY or GEMINI_API_KEY. Add them to your .env file.")
        st.stop()

    if conn is not None and not user_name:
        st.warning("Enter your name in the sidebar first, so your history stays separate from other users'.")
        st.stop()

    if not url:
        st.warning("Enter a URL first.")
        st.stop()

    try:
        video_id = parse_video_id(url)
    except InvalidURLError as exc:
        st.error(str(exc))
        st.stop()

    with st.spinner("Fetching video metadata..."):
        try:
            meta = fetch_metadata(video_id, YOUTUBE_API_KEY)
        except VideoNotFoundError as exc:
            st.error(str(exc))
            st.stop()
        except Exception as exc:
            st.error(f"Failed to fetch video metadata: {exc}")
            st.stop()

    with st.spinner("Fetching transcript..."):
        transcript_segments = fetch_transcript_segments(video_id)
        transcript = segments_to_text(transcript_segments) if transcript_segments else None

    if not transcript:
        st.info("No transcript available for this video. Tags, chapters, hook analysis, keyword density, and pacing will be limited.")

    with st.spinner("Fetching comments..."):
        top_comments = fetch_top_comments(video_id, YOUTUBE_API_KEY)

    competitors = []
    if include_competitors:
        with st.spinner("Finding competing videos..."):
            competitors = find_competitors(meta.title, YOUTUBE_API_KEY, exclude_video_id=video_id)

    cached_result = get_cached_analysis(conn, user_name, video_id) if conn is not None else None
    if cached_result is not None:
        result = cached_result
        st.info("This video was analyzed before — loaded from history, 0 Gemini calls spent.")
    else:
        with st.spinner("Generating SEO suggestions..."):
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
                st.error(f"LLM request failed: {exc}")
                st.stop()

        if conn is not None:
            try:
                save_analysis(conn, user_name, video_id, meta.title, meta.channel_title, result)
            except Exception:
                pass  # history is best-effort, never block the page over it

    # Persisted rather than rendered inline: the on-demand thumbnail button
    # below triggers its own script rerun, which would otherwise wipe out
    # everything computed in this block before it gets a chance to render.
    st.session_state["current_analysis"] = {
        "meta": meta, "result": result, "top_comments": top_comments,
        "competitors": competitors, "include_competitors": include_competitors,
        "transcript_segments": transcript_segments, "transcript_text": transcript,
    }
    st.session_state.pop("thumbnail_review", None)

if st.session_state.get("load_row"):
    row = st.session_state["load_row"]
    result = get_analysis(conn, user_name, row["id"]) if conn is not None else None

    if result is None:
        st.warning("Saved analysis not found — it may have been deleted.")
    else:
        st.subheader(row["title"])
        st.caption(f"{row['channel']} · saved {row['analyzed_at']:%Y-%m-%d %H:%M}")
        st.info(
            "Loaded from history — no API quota spent. Competitors, thumbnail review, "
            "SEO diff, keyword density, and pacing are not stored; re-run Analyze for those."
        )

        render_health_score(row["title"], result.get("description", ""), result.get("tags", []), result.get("hashtags", []))
        render_export_buttons(row["video_id"], row["title"], result)
        render_limit_checks(row["title"], result.get("description", ""), result.get("tags", []), result.get("hashtags", []))

        (
            tags_tab, titles_tab, description_tab, hashtags_tab, chapters_tab,
            hook_tab, comments_tab, shorts_tab, social_tab, suggestions_tab,
        ) = st.tabs([
            "Tags", "Titles", "Description", "Hashtags", "Chapters",
            "Hook", "Comments", "Shorts Script", "Social Posts", "Suggestions",
        ])
        render_core_tabs(
            {
                "tags": tags_tab, "titles": titles_tab, "description": description_tab,
                "hashtags": hashtags_tab, "chapters": chapters_tab, "hook": hook_tab,
                "suggestions": suggestions_tab,
            },
            [], result,
        )
        with comments_tab:
            render_comment_sentiment(result.get("comment_sentiment", {}))
        with shorts_tab:
            render_shorts_scripts(result)
        with social_tab:
            render_social_posts(result)

elif st.session_state.get("current_analysis"):
    data = st.session_state["current_analysis"]
    meta = data["meta"]
    result = data["result"]
    top_comments = data["top_comments"]
    competitors = data["competitors"]
    include_competitors = data["include_competitors"]
    transcript_segments = data["transcript_segments"]
    transcript_text = data["transcript_text"]

    st.subheader(meta.title)
    st.caption(meta.channel_title)

    render_health_score(meta.title, result.get("description", ""), result.get("tags", []), result.get("hashtags", []))
    render_export_buttons(meta.video_id, meta.title, result)
    render_limit_checks(meta.title, result.get("description", ""), result.get("tags", []), result.get("hashtags", []))

    (
        tags_tab, titles_tab, description_tab, hashtags_tab, chapters_tab,
        hook_tab, comments_tab, competitors_tab, thumbnail_tab, suggestions_tab,
        seo_diff_tab, keywords_tab, pacing_tab, shorts_tab, social_tab,
    ) = st.tabs([
        "Tags", "Titles", "Description", "Hashtags", "Chapters",
        "Hook", "Comments", "Competitors", "Thumbnail", "Suggestions",
        "SEO Diff", "Keywords", "Pacing", "Shorts Script", "Social Posts",
    ])

    render_core_tabs(
        {
            "tags": tags_tab, "titles": titles_tab, "description": description_tab,
            "hashtags": hashtags_tab, "chapters": chapters_tab, "hook": hook_tab,
            "suggestions": suggestions_tab,
        },
        meta.tags, result,
    )

    with comments_tab:
        if not top_comments:
            st.info("No comments available for this video (comments may be disabled).")
        else:
            st.caption(f"Based on the top {len(top_comments)} comments by relevance")
            render_comment_sentiment(result.get("comment_sentiment", {}))

    with competitors_tab:
        if not include_competitors:
            st.info("Enable \"Include competitor comparison\" above and re-run to see this.")
        elif not competitors:
            st.info("No competing videos found.")
        else:
            for c in competitors:
                st.markdown(f"**{html.escape(c.title)}**")
                st.caption(c.channel_title)
                if c.tags:
                    chips = "".join(f"<span>{html.escape(t)}</span>" for t in c.tags[:15])
                    st.markdown(f'<div class="tag-chips">{chips}</div>', unsafe_allow_html=True)
                else:
                    st.caption("No public tags")
                st.divider()

            st.markdown("**Keyword gap vs. competitors**")
            gaps = tag_gap(meta.tags + result.get("tags", []), competitors)
            if gaps:
                st.caption("Tags your competitors use that you don't have yet, ranked by how many share them")
                chips = "".join(f"<span>{html.escape(t)} · {n}</span>" for t, n in gaps)
                st.markdown(f'<div class="tag-chips">{chips}</div>', unsafe_allow_html=True)
            else:
                st.caption("No keyword gaps found — your tags already cover what competitors use.")

    with seo_diff_tab:
        tag_diff = diff_tags(meta.tags, result.get("tags", []))
        st.caption(f"{len(tag_diff.added)} new tags suggested · {len(tag_diff.kept)} kept · {len(tag_diff.removed)} of your existing tags dropped")
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Added**")
            for t in tag_diff.added:
                st.markdown(f"- {t}")
            if not tag_diff.added:
                st.caption("None")
        with col2:
            st.markdown("**Dropped**")
            for t in tag_diff.removed:
                st.markdown(f"- {t}")
            if not tag_diff.removed:
                st.caption("None")
        st.divider()
        st.markdown("**Description changes**")
        description_diff = diff_description(meta.description, result.get("description", ""))
        if description_diff:
            st.code("\n".join(description_diff), language="diff")
        else:
            st.caption("No meaningful description changes.")

    with keywords_tab:
        if not transcript_text:
            st.info("Keyword density needs a transcript, which was not available for this video.")
        else:
            bigrams = top_ngrams(transcript_text, 2)
            trigrams = top_ngrams(transcript_text, 3)
            st.caption("Top 2-word phrases")
            if bigrams:
                st.bar_chart(pd.DataFrame({"count": dict(bigrams)}))
            else:
                st.caption("Not enough transcript text for 2-word phrases.")
            st.caption("Top 3-word phrases")
            if trigrams:
                st.bar_chart(pd.DataFrame({"count": dict(trigrams)}))
            else:
                st.caption("Not enough transcript text for 3-word phrases.")

    with pacing_tab:
        if not transcript_segments:
            st.info("Pacing analysis needs a transcript, which was not available for this video.")
        else:
            blocks = words_per_minute_blocks(transcript_segments)
            df = pd.DataFrame({"WPM": [b.wpm for b in blocks]}, index=[f"{b.minute}m" for b in blocks])
            st.line_chart(df)
            gaps = find_silent_gaps(transcript_segments)
            if gaps:
                st.caption(f"{len(gaps)} silent gap(s) longer than {SILENT_GAP_THRESHOLD_SECONDS:.0f}s")
                for g in gaps[:10]:
                    st.markdown(f"- {g.start:.0f}s to {g.end:.0f}s ({g.duration:.1f}s gap)")
            else:
                st.caption("No notable silent gaps detected.")

    with shorts_tab:
        render_shorts_scripts(result)

    with social_tab:
        render_social_posts(result)

    with thumbnail_tab:
        if meta.thumbnail_url:
            st.image(meta.thumbnail_url, width=320)

        thumbnail_review = st.session_state.get("thumbnail_review")
        if thumbnail_review is None:
            if st.button("Run Thumbnail Vision Critique"):
                with st.spinner("Analyzing thumbnail..."):
                    st.session_state["thumbnail_review"] = critique_thumbnail(GEMINI_API_KEYS, meta.thumbnail_url) or {}
                st.rerun()
        elif not thumbnail_review:
            st.info("Thumbnail review unavailable for this video.")
        else:
            checks = [
                ("Legible at small size", thumbnail_review.get("legible_at_small_size")),
                ("Clear focal point", thumbnail_review.get("has_clear_focal_point")),
                ("Stands out in a busy feed", thumbnail_review.get("stands_out_in_feed")),
            ]
            for label, ok in checks:
                st.markdown(f"{'Yes' if ok else 'No'} — {label}")
            if thumbnail_review.get("feedback"):
                st.write(thumbnail_review["feedback"])
