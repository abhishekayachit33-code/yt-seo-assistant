from youtube_transcript_api import YouTubeTranscriptApi


def fetch_transcript_text(video_id: str, max_chars: int = 12000) -> str | None:
    try:
        fetched = YouTubeTranscriptApi().fetch(video_id)
    except Exception:
        return None

    lines = []
    total = 0
    for snippet in fetched:
        minutes, seconds = divmod(int(snippet.start), 60)
        line = f"[{minutes:02d}:{seconds:02d}] {snippet.text}"
        total += len(line)
        if total > max_chars:
            break
        lines.append(line)

    return "\n".join(lines) if lines else None
