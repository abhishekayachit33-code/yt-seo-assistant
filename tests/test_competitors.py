from competitors import CompetitorVideo, audience_gap, steal_tags


def competitor(views: int, tags: list[str], name: str = "rival") -> CompetitorVideo:
    return CompetitorVideo(
        video_id=name, title=name, channel_title=name, tags=tags, view_count=views
    )


def test_gap_is_median_of_top_three_minus_own_views():
    competitors = [
        competitor(600_000, []),
        competitor(450_000, []),
        competitor(300_000, []),
        competitor(10, []),  # 4th place must not enter the comparison
    ]
    gap = audience_gap(10_000, [], competitors)
    assert gap.competitor_median_views == 450_000
    assert gap.gap == 440_000
    assert len(gap.top_competitors) == 3


def test_a_viral_outlier_does_not_define_the_gap():
    """The failure this replaced: mean over 4M/7k/6k reported 1,337,667 and
    told a creator at 5,000 views their addressable gap was 1.3 million."""
    competitors = [
        competitor(4_000_000, [], "viral"),
        competitor(7_000, [], "peer_a"),
        competitor(6_000, [], "peer_b"),
    ]
    gap = audience_gap(5_000, [], competitors)
    assert gap.competitor_median_views == 6_500
    assert gap.gap == 1_500


def test_the_outlier_is_disclosed_not_hidden():
    competitors = [
        competitor(4_000_000, [], "viral"),
        competitor(7_000, [], "peer_a"),
        competitor(6_000, [], "peer_b"),
    ]
    gap = audience_gap(5_000, [], competitors)
    assert gap.has_outliers
    assert [c.channel_title for c in gap.outliers] == ["viral"]
    # Still shown as a competitor -- it really is ranking for these words.
    assert len(gap.top_competitors) == 3


def test_a_uniformly_large_field_has_no_outliers():
    """Outliers are relative to the set, so a field of comparable big
    channels is not flagged -- there is nothing anomalous about it."""
    competitors = [competitor(500_000, []), competitor(600_000, []), competitor(400_000, [])]
    gap = audience_gap(1_000, [], competitors)
    assert not gap.has_outliers


def test_gap_never_goes_negative_when_already_ahead():
    gap = audience_gap(900_000, [], [competitor(100_000, [])])
    assert gap.gap == 0


def test_no_competitors_returns_none():
    assert audience_gap(1000, [], []) is None


def test_steal_tags_rank_by_competitor_consensus_not_views():
    """Deliberate reversal. View-weighting let one big channel's tag outrank a
    tag two comparable channels independently converged on -- measured on a
    realistic set it promoted "study abroad", "germany vlog" and "travel" over
    "aps certificate germany". One competitor is one vote, whatever its size."""
    competitors = [
        competitor(500_000, ["streamlit deployment"], "big"),
        competitor(5_000, ["niche tag"], "small_a"),
        competitor(5_000, ["niche tag"], "small_b"),
    ]
    ranked = steal_tags([], competitors)
    assert ranked[0] == ("niche tag", 2)


def test_one_video_repeating_a_tag_cannot_manufacture_consensus():
    ranked = steal_tags([], [competitor(100, ["repeated", "repeated", "repeated"])])
    assert ranked == [("repeated", 1)]


def test_steal_tags_ordering_is_deterministic_for_ties():
    """Counter.most_common leaves ties in insertion order, which would make
    output depend on the order the search API returned videos in."""
    a = steal_tags([], [competitor(10, ["zebra", "alpha"], "x")])
    b = steal_tags([], [competitor(10, ["alpha", "zebra"], "x")])
    assert a == b == [("alpha", 1), ("zebra", 1)]


def test_steal_tags_excludes_tags_already_used_case_insensitively():
    competitors = [competitor(100, ["Already Have", "missing one"])]
    ranked = steal_tags(["already have"], competitors)
    assert [t for t, _ in ranked] == ["missing one"]


def test_zero_view_competitor_tags_still_rank_above_nothing():
    ranked = steal_tags([], [competitor(0, ["obscure"])])
    assert ranked == [("obscure", 1)]
