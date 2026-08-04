import html
import os

import streamlit as st
from dotenv import load_dotenv

from comments import fetch_top_comments, summarize_comments
from competitors import find_competitors
from limits import check_limits
from llm import generate_seo
from transcript import fetch_transcript_text
from youtube import InvalidURLError, VideoNotFoundError, fetch_metadata, parse_video_id

load_dotenv()

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

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

st.title("YouTube SEO Assistant")
st.caption("Paste a video URL to generate SEO tags, titles, descriptions, chapters, and reach suggestions.")

url = st.text_input("YouTube video URL", placeholder="https://www.youtube.com/watch?v=...")
include_competitors = st.checkbox(
    "Include competitor comparison",
    help="Uses 100x more YouTube API quota than a routine analysis. Off by default.",
)
run = st.button("Analyze")

if run:
    if not YOUTUBE_API_KEY or not GEMINI_API_KEY:
        st.error("Missing YOUTUBE_API_KEY or GEMINI_API_KEY. Add them to your .env file.")
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

    st.subheader(meta.title)
    st.caption(meta.channel_title)

    with st.spinner("Fetching transcript..."):
        transcript = fetch_transcript_text(video_id)

    if not transcript:
        st.info("No transcript available for this video. Tags, chapters, and hook analysis will be limited.")

    with st.spinner("Fetching comments..."):
        top_comments = fetch_top_comments(video_id, YOUTUBE_API_KEY)
        comment_summary = summarize_comments(GEMINI_API_KEY, top_comments) if top_comments else None

    competitors = []
    if include_competitors:
        with st.spinner("Finding competing videos..."):
            competitors = find_competitors(meta.title, YOUTUBE_API_KEY, exclude_video_id=video_id)

    with st.spinner("Generating SEO suggestions..."):
        try:
            result = generate_seo(
                api_key=GEMINI_API_KEY,
                title=meta.title,
                description=meta.description,
                existing_tags=meta.tags,
                transcript=transcript,
            )
        except Exception as exc:
            st.error(f"LLM request failed: {exc}")
            st.stop()

    tags = result.get("tags", [])
    titles = result.get("titles", [])
    description = result.get("description", "")
    hashtags = result.get("hashtags", [])
    chapters = result.get("chapters", [])
    suggestions = result.get("suggestions", [])
    hook = result.get("hook_analysis", {})

    limit_checks = check_limits(meta.title, description, tags, hashtags)
    cards = "".join(
        f'<div class="limit-card {"ok" if c.ok else "fail"}">'
        f'<div class="label">{html.escape(c.label)}</div>'
        f'<div class="value">{c.current}/{c.maximum}</div>'
        f"</div>"
        for c in limit_checks
    )
    st.markdown(f'<div class="limit-grid">{cards}</div>', unsafe_allow_html=True)
    if any(not c.ok for c in limit_checks):
        st.warning("One or more fields exceed YouTube's limits — trim before publishing.")

    (
        tags_tab, titles_tab, description_tab, hashtags_tab,
        chapters_tab, hook_tab, comments_tab, competitors_tab, suggestions_tab,
    ) = st.tabs([
        "Tags", "Titles", "Description", "Hashtags",
        "Chapters", "Hook", "Comments", "Competitors", "Suggestions",
    ])

    with tags_tab:
        joined = ", ".join(tags)
        st.caption(f"{len(tags)} tags · {len(joined)}/500 characters")

        existing_lower = {t.lower() for t in meta.tags}
        chips = "".join(
            f'<span class="{"existing" if t.lower() in existing_lower else ""}">{html.escape(t)}</span>'
            for t in tags
        )
        st.markdown(f'<div class="tag-chips">{chips}</div>', unsafe_allow_html=True)
        if meta.tags:
            st.caption(f"{len(existing_lower & {t.lower() for t in tags})} of your existing {len(meta.tags)} tags were kept; the rest are new suggestions.")

        st.caption("Copy for the tags field")
        st.code(joined, language=None)

    with titles_tab:
        if titles:
            for i, t in enumerate(titles, 1):
                st.markdown(f"**{i}.** {t}  \n<span style='color:#9CA3AF;font-size:0.78rem'>{len(t)}/100 characters</span>", unsafe_allow_html=True)
        else:
            st.info("No title suggestions generated.")

    with description_tab:
        if description:
            st.text_area("Optimized description", description, height=280, label_visibility="collapsed")
        else:
            st.info("No description generated.")

    with hashtags_tab:
        st.caption(f"{len(hashtags)}/15 hashtags")
        chips = "".join(f"<span>{html.escape(h)}</span>" for h in hashtags)
        st.markdown(f'<div class="tag-chips">{chips}</div>', unsafe_allow_html=True)
        st.code(" ".join(hashtags), language=None)

    with chapters_tab:
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

    with hook_tab:
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

    with comments_tab:
        if not top_comments:
            st.info("No comments available for this video (comments may be disabled).")
        else:
            st.caption(f"Based on the top {len(top_comments)} comments by relevance")
            if comment_summary and comment_summary.get("summary"):
                st.write(comment_summary["summary"])
            positive = (comment_summary or {}).get("positive_themes", [])
            negative = (comment_summary or {}).get("negative_themes", [])
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

    with suggestions_tab:
        for i, suggestion in enumerate(suggestions, 1):
            st.markdown(f"**{i}.** {suggestion}")
