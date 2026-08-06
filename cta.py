"""Call-to-action placement analysis.

Finds where a video asks for something -- a subscribe, a click, a signup -- and
judges the timing against retention reality: an ask in the final stretch reaches
only the fraction of viewers who stayed, while an ask before any value is
delivered reaches people with no reason yet to say yes.
"""

import re
from dataclasses import dataclass

from transcript import TranscriptSegment

# Fractions of total runtime. The prime window is the stretch where a viewer has
# seen enough to be convinced but has not yet started dropping off.
TOO_EARLY_BEFORE = 0.05
PRIME_START = 0.05
PRIME_END = 0.70
LATE_END = 0.90
RECOMMENDED_POSITION = 0.35

CTA_PATTERNS = {
    "subscribe": r"\bsubscrib(?:e|ing)\b",
    "like the video": r"\b(?:hit|smash|leave|drop) (?:that |the |a )?like\b",
    "notification bell": r"\b(?:notification )?bell\b|\bturn on notifications\b",
    "link in description": r"\blink(?:s)? (?:in|below|down in) (?:the )?(?:description|bio|comments)\b",
    "check it out": r"\bcheck (?:it|them|this|that) out\b|\bcheck out (?:my|the|our)\b",
    "sign up": r"\bsign up\b|\bsignup\b|\bregister (?:for|at)\b",
    "discount code": r"\b(?:use|with) (?:my |the )?(?:code|coupon)\b|\bdiscount code\b",
    "comment below": r"\b(?:comment|let me know) (?:below|down below|in the comments)\b",
    "follow": r"\bfollow me\b|\bfollow us\b",
    "join": r"\bjoin (?:my|our|the) (?:channel|community|discord|patreon|newsletter)\b",
}

_COMPILED = {label: re.compile(pattern, re.IGNORECASE) for label, pattern in CTA_PATTERNS.items()}

TOO_EARLY = "too early"
WELL_PLACED = "well placed"
LATE = "late"
TOO_LATE = "too late"


@dataclass
class CTAMention:
    seconds: float
    position: float  # 0.0-1.0 through the video
    label: str
    text: str
    zone: str

    @property
    def timestamp(self) -> str:
        minutes, seconds = divmod(int(self.seconds), 60)
        return f"{minutes:02d}:{seconds:02d}"


@dataclass
class CTAReport:
    duration: float
    mentions: list[CTAMention]
    recommended_seconds: float

    @property
    def recommended_timestamp(self) -> str:
        minutes, seconds = divmod(int(self.recommended_seconds), 60)
        return f"{minutes:02d}:{seconds:02d}"

    @property
    def has_well_placed(self) -> bool:
        return any(m.zone == WELL_PLACED for m in self.mentions)

    @property
    def stranded(self) -> list[CTAMention]:
        """Asks that land where most of the audience has already gone."""
        return [m for m in self.mentions if m.zone == TOO_LATE]


def zone_for(position: float) -> str:
    if position < TOO_EARLY_BEFORE:
        return TOO_EARLY
    if position <= PRIME_END:
        return WELL_PLACED
    if position <= LATE_END:
        return LATE
    return TOO_LATE


def analyze_ctas(segments: list[TranscriptSegment] | None) -> CTAReport | None:
    """None when there is no transcript to read. A transcript with no asks at
    all still returns a report -- never asking is itself worth surfacing."""
    if not segments:
        return None

    duration = max(s.start + s.duration for s in segments)
    if duration <= 0:
        return None

    mentions: list[CTAMention] = []
    for segment in segments:
        for label, pattern in _COMPILED.items():
            if pattern.search(segment.text):
                position = min(segment.start / duration, 1.0)
                mentions.append(
                    CTAMention(
                        seconds=segment.start,
                        position=position,
                        label=label,
                        text=segment.text.strip(),
                        zone=zone_for(position),
                    )
                )
                break  # one mention per line, even if it stacks several asks

    return CTAReport(
        duration=duration,
        mentions=mentions,
        recommended_seconds=duration * RECOMMENDED_POSITION,
    )
