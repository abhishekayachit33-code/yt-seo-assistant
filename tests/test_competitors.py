from competitors import CompetitorVideo, audience_gap, steal_tags


def competitor(views: int, tags: list[str], name: str = "rival") -> CompetitorVideo:
    return CompetitorVideo(
        video_id=name, title=name, channel_title=name, tags=tags, view_count=views
    )


def test_gap_is_average_of_top_three_minus_own_views():
    competitors = [
        competitor(600_000, []),
        competitor(450_000, []),
        competitor(300_000, []),
        competitor(10, []),  # 4th place must not drag the average down
    ]
    gap = audience_gap(10_000, [], competitors)
    assert gap.competitor_average_views == 450_000
    assert gap.gap == 440_000
    assert len(gap.top_competitors) == 3


def test_gap_never_goes_negative_when_already_ahead():
    gap = audience_gap(900_000, [], [competitor(100_000, [])])
    assert gap.gap == 0


def test_no_competitors_returns_none():
    assert audience_gap(1000, [], []) is None


def test_steal_tags_rank_by_views_behind_them_not_frequency():
    competitors = [
        competitor(500_000, ["streamlit deployment"], "big"),
        competitor(5_000, ["niche tag"], "small_a"),
        competitor(5_000, ["niche tag"], "small_b"),
    ]
    ranked = steal_tags([], competitors)
    # "niche tag" appears on more videos, but the half-million-view tag wins.
    assert ranked[0][0] == "streamlit deployment"
    assert ranked[0][1] == 500_000


def test_steal_tags_excludes_tags_already_used_case_insensitively():
    competitors = [competitor(100, ["Already Have", "missing one"])]
    ranked = steal_tags(["already have"], competitors)
    assert [t for t, _ in ranked] == ["missing one"]


def test_zero_view_competitor_tags_still_rank_above_nothing():
    ranked = steal_tags([], [competitor(0, ["obscure"])])
    assert ranked == [("obscure", 1)]
