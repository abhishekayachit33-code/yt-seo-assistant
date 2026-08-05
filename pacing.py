from dataclasses import dataclass

from transcript import TranscriptSegment

SILENT_GAP_THRESHOLD_SECONDS = 3.0


@dataclass
class PacingBlock:
    minute: int
    words: int
    wpm: int


@dataclass
class SilentGap:
    start: float
    end: float
    duration: float


def words_per_minute_blocks(segments: list[TranscriptSegment], block_seconds: int = 60) -> list[PacingBlock]:
    """Word count per fixed time block, scaled to a words-per-minute rate --
    flags parts of the video that talk much faster or slower than the rest."""
    if not segments:
        return []

    end_time = segments[-1].start + segments[-1].duration
    num_blocks = int(end_time // block_seconds) + 1
    word_counts = [0] * num_blocks

    for s in segments:
        block = min(int(s.start // block_seconds), num_blocks - 1)
        word_counts[block] += len(s.text.split())

    scale = 60 / block_seconds
    return [
        PacingBlock(minute=i, words=w, wpm=round(w * scale))
        for i, w in enumerate(word_counts)
    ]


def find_silent_gaps(segments: list[TranscriptSegment], threshold: float = SILENT_GAP_THRESHOLD_SECONDS) -> list[SilentGap]:
    """Gaps between consecutive spoken lines longer than threshold -- likely
    dead air, a pause, or a visual-only beat with no narration."""
    gaps = []
    for prev, curr in zip(segments, segments[1:]):
        prev_end = prev.start + prev.duration
        gap = curr.start - prev_end
        if gap > threshold:
            gaps.append(SilentGap(start=prev_end, end=curr.start, duration=gap))
    return gaps
