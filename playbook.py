"""Growth playbook: a ranked, concrete punch list synthesized from analysis
this app has already computed elsewhere -- the metadata health checklist, the
audience gap, CTA placement, and shelf life. No extra API call; it is pure
recombination of existing results into one prioritized "do this next" view.

Ranked by how directly each item ties to view count, most concrete first:
missing keywords with a known view value behind them, a stranded call to
action, then hard compliance failures, then framing/context notes.
"""

from dataclasses import dataclass

from limits import HealthRule


@dataclass
class Action:
    title: str
    detail: str
    icon: str


def build_playbook(
    optimized_rules: list[HealthRule],
    gap=None,
    cta_report=None,
    shelf=None,
    thumbnail_review: dict | None = None,
) -> list[Action]:
    actions: list[Action] = []

    if gap is not None and gap.missing_tags:
        top = gap.missing_tags[:4]
        tag_list = ", ".join(f'"{t}"' for t, _ in top)
        actions.append(
            Action(
                f"Add {len(top)} keyword{'s' if len(top) != 1 else ''} your competitors agree on",
                f"{tag_list} — each used by several competing videos independently, which is "
                "evidence about this niche's vocabulary rather than one channel's guess. "
                f"The median competitor sits at {gap.competitor_median_views:,} views.",
                ":material/swap_horiz:",
            )
        )

    if cta_report is not None:
        for mention in cta_report.stranded:
            actions.append(
                Action(
                    f'Move your "{mention.label}" ask earlier',
                    f"It currently lands at {mention.timestamp} ({mention.position:.0%} into the video), "
                    f"after most viewers have already left. Move it to around "
                    f"{cta_report.recommended_timestamp}, while they are still watching.",
                    ":material/campaign:",
                )
            )
        if not cta_report.mentions:
            actions.append(
                Action(
                    "Add a call to action",
                    "The transcript never asks viewers to subscribe, click, or sign up. "
                    f"Add one around {cta_report.recommended_timestamp} — silence here is a missed ask, not a neutral choice.",
                    ":material/campaign:",
                )
            )

    for rule in optimized_rules:
        if not rule.passed:
            actions.append(
                Action(
                    rule.label,
                    f"Currently: {rule.detail}. This is one of the metadata health checklist items — "
                    "fixing it raises the health score, which directly feeds the reach projection.",
                    ":material/health_metrics:",
                )
            )

    if thumbnail_review:
        weak_points = [
            label for label, ok in [
                ("legible at small size", thumbnail_review.get("legible_at_small_size")),
                ("a clear focal point", thumbnail_review.get("has_clear_focal_point")),
                ("standing out in a busy feed", thumbnail_review.get("stands_out_in_feed")),
            ] if not ok
        ]
        if weak_points:
            actions.append(
                Action(
                    "Redo the thumbnail",
                    f"The vision critique flagged it as weak on {', '.join(weak_points)} — "
                    "the thumbnail is most of what decides a click before anyone reads the title.",
                    ":material/image_search:",
                )
            )

    if shelf is not None and shelf.classification in ("Trending", "Mostly trending"):
        actions.append(
            Action(
                "Plan for a short shelf life",
                f"This reads as {shelf.classification.lower()} — {shelf.expectation} "
                "Consider a follow-up evergreen video on the same topic (a \"how to\" or \"explained\" "
                "framing) to keep earning search traffic after the initial spike fades.",
                ":material/hourglass:",
            )
        )

    return actions


READY = "ready"
NEEDS_WORK = "needs_work"
UNKNOWN = "unknown"

_WEAK_HOOK_SIGNALS = ("weak", "slow", "poor", "unclear", "fails", "doesn't hook", "does not hook")

HEALTH_SCORE_READY_THRESHOLD = 80
SHORT_LENGTH_MINUTES = 2
LONG_LENGTH_MINUTES = 30


@dataclass
class ChecklistItem:
    label: str
    status: str  # "ready" | "needs_work" | "unknown"
    detail: str


@dataclass
class PreproductionChecklist:
    items: list[ChecklistItem]

    @property
    def ready_to_record(self) -> bool:
        return all(i.status != NEEDS_WORK for i in self.items)


def build_preproduction_checklist(
    health_score: int,
    hook_analysis: dict,
    speech_estimate=None,
    shelf=None,
) -> PreproductionChecklist:
    """Pure recombination of signals this app has already computed elsewhere
    -- same no-I/O shape as build_playbook -- into a single go/no-go read
    before recording. Each item degrades to 'unknown' rather than a false
    'needs_work' when the underlying data (a pasted script, a hook verdict)
    simply wasn't provided; missing data is not the same as a problem."""
    items = []

    verdict = (hook_analysis or {}).get("verdict", "")
    if not verdict or verdict == "unavailable":
        items.append(ChecklistItem(
            "Hook strength", UNKNOWN,
            "No script was pasted, so the opening couldn't be judged.",
        ))
    elif any(signal in verdict.lower() for signal in _WEAK_HOOK_SIGNALS):
        items.append(ChecklistItem(
            "Hook strength", NEEDS_WORK,
            f"Verdict: {verdict}. Tighten the first ~30 seconds before recording.",
        ))
    else:
        items.append(ChecklistItem("Hook strength", READY, f"Verdict: {verdict}."))

    if health_score >= HEALTH_SCORE_READY_THRESHOLD:
        items.append(ChecklistItem(
            "Metadata health", READY, f"{health_score}% -- above the {HEALTH_SCORE_READY_THRESHOLD}% bar.",
        ))
    else:
        items.append(ChecklistItem(
            "Metadata health", NEEDS_WORK,
            f"{health_score}% -- check the compliance checklist before publishing.",
        ))

    if speech_estimate is None:
        items.append(ChecklistItem(
            "Estimated length", UNKNOWN, "No script was pasted, so length couldn't be estimated.",
        ))
    elif speech_estimate.high_minutes < SHORT_LENGTH_MINUTES:
        items.append(ChecklistItem(
            "Estimated length", NEEDS_WORK,
            f"{speech_estimate.label} -- unusually short for long-form; confirm this is intentional (e.g. a Short).",
        ))
    elif speech_estimate.low_minutes > LONG_LENGTH_MINUTES:
        items.append(ChecklistItem(
            "Estimated length", NEEDS_WORK,
            f"{speech_estimate.label} -- long enough that retention may suffer without a strong structure.",
        ))
    else:
        items.append(ChecklistItem("Estimated length", READY, speech_estimate.label))

    if shelf is None:
        items.append(ChecklistItem("Shelf-life framing", UNKNOWN, "Not enough signal to classify."))
    else:
        # Informational only, never a blocker -- a Trending classification is
        # a fact to plan distribution around, not a defect to fix.
        items.append(ChecklistItem(
            "Shelf-life framing", READY, f"{shelf.classification}: {shelf.expectation}",
        ))

    return PreproductionChecklist(items=items)
