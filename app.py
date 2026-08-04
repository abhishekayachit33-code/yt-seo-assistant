import html
import os

import streamlit as st
from dotenv import load_dotenv

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
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("YouTube SEO Assistant")
st.caption("Paste a video URL to generate SEO tags, chapter timestamps, and reach suggestions.")

url = st.text_input("YouTube video URL", placeholder="https://www.youtube.com/watch?v=...")
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
        st.info("No transcript available for this video. Tags and suggestions will be based on title, description, and existing tags only.")

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

    tags_tab, chapters_tab, suggestions_tab = st.tabs(["Tags", "Chapters", "Suggestions"])

    with tags_tab:
        tags = result.get("tags", [])
        joined = ", ".join(tags)
        st.caption(f"{len(tags)} tags · {len(joined)}/500 characters")
        if len(joined) > 500:
            st.warning("Over YouTube's 500-character tag limit. Trim before pasting.")

        chips = "".join(f"<span>{html.escape(t)}</span>" for t in tags)
        st.markdown(f'<div class="tag-chips">{chips}</div>', unsafe_allow_html=True)

        st.caption("Copy for the tags field")
        st.code(joined, language=None)

    with chapters_tab:
        chapters = result.get("chapters", [])
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

    with suggestions_tab:
        for i, suggestion in enumerate(result.get("suggestions", []), 1):
            st.markdown(f"**{i}.** {suggestion}")
