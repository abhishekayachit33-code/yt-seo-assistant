from dataclasses import dataclass

from youtube_transcript_api import YouTubeTranscriptApi


@dataclass
class TranscriptSegment:
    start: float
    duration: float
    text: str


def fetch_transcript_segments(video_id: str) -> list[TranscriptSegment] | None:
    """Raw timed segments, untruncated. None if no transcript is available --
    never raises, callers degrade gracefully (no chapters/hook/pacing/keywords)."""
    try:
        fetched = YouTubeTranscriptApi().fetch(video_id)
    except Exception:
        return None

    segments = [
        TranscriptSegment(start=s.start, duration=s.duration, text=s.text)
        for s in fetched
    ]
    return segments or None


def segments_to_text(segments: list[TranscriptSegment], max_chars: int = 12000) -> str | None:
    """Timestamped text, truncated to max_chars -- what gets sent to Gemini,
    kept short to bound prompt size/cost."""
    lines = []
    total = 0
    for s in segments:
        minutes, seconds = divmod(int(s.start), 60)
        line = f"[{minutes:02d}:{seconds:02d}] {s.text}"
        total += len(line)
        if total > max_chars:
            break
        lines.append(line)
    return "\n".join(lines) if lines else None


def fetch_transcript_text(video_id: str, max_chars: int = 12000) -> str | None:
    segments = fetch_transcript_segments(video_id)
    if not segments:
        return None
    return segments_to_text(segments, max_chars)
