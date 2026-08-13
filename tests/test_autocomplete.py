import json
from unittest.mock import MagicMock, patch

import requests

from autocomplete import MAX_QUERIES, build_queries, collect, fetch_suggestions


def test_build_queries_puts_bare_seeds_first():
    queries = build_queries(["germany", "visa"])
    assert queries[0] == "germany"
    assert queries[1] == "visa"


def test_build_queries_respects_the_budget_cap():
    # 6 seeds x (1 bare + 6 question + 4 comparison + 26 letters) far exceeds
    # the cap; the cap is what stops an unofficial endpoint being hammered.
    queries = build_queries([f"seed{i}" for i in range(6)])
    assert len(queries) == MAX_QUERIES


def test_build_queries_deduplicates():
    queries = build_queries(["germany", "germany"])
    assert len(queries) == len(set(queries))


def test_build_queries_empty_seeds_gives_nothing():
    assert build_queries([]) == []


def _suggest_response(phrases):
    response = MagicMock()
    response.text = json.dumps(["seed", phrases, [], {}])
    response.raise_for_status = lambda: None
    return response


@patch("autocomplete.requests.get")
def test_fetch_suggestions_parses_the_payload(mock_get):
    mock_get.return_value = _suggest_response(["study in germany", "study in germany for indians"])
    assert fetch_suggestions("study in germany") == [
        "study in germany", "study in germany for indians",
    ]


@patch("autocomplete.requests.get")
def test_fetch_suggestions_sends_region_and_language(mock_get):
    mock_get.return_value = _suggest_response([])
    fetch_suggestions("x", region="IN", language="en")
    params = mock_get.call_args.kwargs["params"]
    assert params["gl"] == "IN"
    assert params["hl"] == "en"
    assert params["ds"] == "yt"


@patch("autocomplete.requests.get")
def test_fetch_suggestions_returns_empty_on_network_failure(mock_get):
    mock_get.side_effect = requests.exceptions.RequestException("blocked")
    assert fetch_suggestions("x") == []


@patch("autocomplete.requests.get")
def test_fetch_suggestions_returns_empty_on_malformed_json(mock_get):
    response = MagicMock()
    response.text = "not json at all"
    response.raise_for_status = lambda: None
    mock_get.return_value = response
    assert fetch_suggestions("x") == []


@patch("autocomplete.requests.get")
def test_fetch_suggestions_survives_unexpected_payload_shape(mock_get):
    response = MagicMock()
    response.text = json.dumps({"unexpected": "shape"})
    response.raise_for_status = lambda: None
    mock_get.return_value = response
    assert fetch_suggestions("x") == []


@patch("autocomplete.fetch_suggestions")
def test_collect_keeps_the_best_rank_across_queries(mock_fetch):
    # "germany visa" comes back 3rd for one query and 1st for another --
    # the stronger position is the one that should survive.
    def fake(query, region, language):
        return ["a", "b", "germany visa"] if query == "germany" else ["germany visa"]
    mock_fetch.side_effect = fake

    results = collect(["germany", "visa"])
    match = next(s for s in results if s.phrase == "germany visa")
    assert match.rank == 0


@patch("autocomplete.fetch_suggestions")
def test_collect_returns_sorted_by_rank(mock_fetch):
    mock_fetch.side_effect = lambda q, r, l: ["first", "second", "third"]
    results = collect(["seed"])
    assert [s.rank for s in results] == sorted(s.rank for s in results)


def test_collect_with_no_seeds_makes_no_requests():
    with patch("autocomplete.fetch_suggestions") as mock_fetch:
        assert collect([]) == []
        mock_fetch.assert_not_called()


@patch("autocomplete.fetch_suggestions")
def test_collect_survives_every_query_failing(mock_fetch):
    mock_fetch.side_effect = lambda q, r, l: []
    assert collect(["germany"]) == []
