from revenue import DEFAULT_RPM, estimate_revenue, rpm_for


def test_known_categories_map_to_their_rpm():
    assert rpm_for("28") == ("Science & Technology", 8.00)
    assert rpm_for("20") == ("Gaming", 2.50)


def test_unknown_or_missing_category_falls_back_to_general_average():
    assert rpm_for("9999") == ("Uncategorised", DEFAULT_RPM)
    assert rpm_for("") == ("Uncategorised", DEFAULT_RPM)


def test_category_id_accepts_int_or_string():
    assert rpm_for(28) == rpm_for("28")


def test_current_revenue_is_views_per_thousand_times_rpm():
    # 100,000 views of tech content at $8.00 RPM = $800.
    estimate = estimate_revenue(100_000, "28")
    assert estimate.current == 800.0
    assert estimate.rpm == 8.00


def test_additional_revenue_tracks_the_uplift_range():
    estimate = estimate_revenue(10_000, "20", additional_views_low=4_000, additional_views_high=8_000)
    assert estimate.current == 25.0  # 10k views at $2.50
    assert estimate.additional_low == 10.0
    assert estimate.additional_high == 20.0


def test_no_uplift_means_no_additional_revenue():
    estimate = estimate_revenue(50_000, "27")
    assert estimate.additional_low == estimate.additional_high == 0


def test_zero_and_negative_inputs_do_not_produce_negative_money():
    estimate = estimate_revenue(0, "28", additional_views_low=-100, additional_views_high=-5)
    assert estimate.current == 0
    assert estimate.additional_low == 0
    assert estimate.additional_high == 0


def test_unknown_category_is_flagged_as_such():
    assert not estimate_revenue(1000, "9999").is_known_category
    assert estimate_revenue(1000, "27").is_known_category
