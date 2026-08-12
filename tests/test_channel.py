from channel import parse_iso8601_duration


def test_parses_hours_minutes_seconds():
    assert parse_iso8601_duration("PT1H2M3S") == 3723


def test_parses_minutes_seconds_only():
    assert parse_iso8601_duration("PT4M13S") == 253


def test_parses_seconds_only():
    assert parse_iso8601_duration("PT45S") == 45


def test_parses_hours_only():
    assert parse_iso8601_duration("PT2H") == 7200


def test_empty_or_invalid_is_zero():
    assert parse_iso8601_duration("") == 0
    assert parse_iso8601_duration("garbage") == 0
