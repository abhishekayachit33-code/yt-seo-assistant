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
                f"Add {len(top)} keyword{'s' if len(top) != 1 else ''} your competitors are winning with",
                f"{tag_list} — ranked by the views sitting behind them on rival videos. "
                f"Your top competitors average {gap.competitor_average_views:,} views; "
                f"these are the tags most likely explaining part of that gap.",
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
