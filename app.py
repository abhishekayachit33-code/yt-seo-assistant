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
        color: #1A73E8;
        border-bottom-color: #1A73E8;
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
        st.write(f"{len(tags)} tags generated")
        st.code(", ".join(tags), language=None)

    with chapters_tab:
        chapters = result.get("chapters", [])
        if chapters:
            for chapter in chapters:
                st.write(f"{chapter.get('timestamp', '')} — {chapter.get('title', '')}")
        else:
            st.info("No chapters generated (transcript was not available).")

    with suggestions_tab:
        for suggestion in result.get("suggestions", []):
            st.write(f"- {suggestion}")
