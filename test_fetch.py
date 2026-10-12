"""Tests for the openfda request layer.

The retry behaviour is the point: openfda rate limits per minute, so a 429 has to be
retried rather than surfaced, and a permanent failure has to give up rather than hang
forever. No network here, requests.get is swapped out.
"""

import pytest
import requests

import fetch

BODY = {"meta": {"results": {"total": 42}}, "results": [{"safetyreportid": "1"}]}


class Response:
    def __init__(self, status_code, body=None, text=""):
        self.status_code = status_code
        self._body = body if body is not None else BODY
        self.text = text

    def json(self):
        return self._body


@pytest.fixture(autouse=True)
def no_sleeping(monkeypatch):
    # the real backoff is 3, 6, 12 seconds, which a test suite should not sit through
    monkeypatch.setattr(fetch.time, "sleep", lambda seconds: None)


def fake_get(responses):
    """A requests.get that returns the given responses in order and counts the calls."""
    calls = []

    def get(url, params=None, timeout=None):
        calls.append(params)
        index = min(len(calls) - 1, len(responses) - 1)
        response = responses[index]
        if isinstance(response, Exception):
            raise response
        return response

    return get, calls


def test_a_429_then_a_200_returns_the_body(monkeypatch):
    get, calls = fake_get([Response(429), Response(200)])
    monkeypatch.setattr(fetch.requests, "get", get)

    body = fetch.get(fetch.BASE_URL, {"search": "x"})
    assert body == BODY
    assert len(calls) == 2


def test_a_500_is_retried(monkeypatch):
    get, calls = fake_get([Response(503), Response(200)])
    monkeypatch.setattr(fetch.requests, "get", get)

    assert fetch.get(fetch.BASE_URL, {}) == BODY
    assert len(calls) == 2


def test_retries_give_up_after_the_maximum(monkeypatch):
    get, calls = fake_get([Response(429)])
    monkeypatch.setattr(fetch.requests, "get", get)

    with pytest.raises(fetch.OpenFdaError) as error:
        fetch.get(fetch.BASE_URL, {})
    assert "gave up" in str(error.value)
    assert len(calls) == fetch.MAX_ATTEMPTS


def test_a_404_means_no_match_and_is_not_retried(monkeypatch):
    # openfda uses 404 for "nothing matched", which is a result and not an error
    get, calls = fake_get([Response(404)])
    monkeypatch.setattr(fetch.requests, "get", get)

    assert fetch.get(fetch.BASE_URL, {}) is None
    assert len(calls) == 1


def test_a_400_is_not_retried(monkeypatch):
    # a bad query will stay bad, so retrying it just wastes the rate limit
    get, calls = fake_get([Response(400, text="bad search")])
    monkeypatch.setattr(fetch.requests, "get", get)

    with pytest.raises(fetch.OpenFdaError):
        fetch.get(fetch.BASE_URL, {})
    assert len(calls) == 1


def test_a_connection_error_is_retried_then_raises(monkeypatch):
    get, calls = fake_get([requests.ConnectionError("dns")])
    monkeypatch.setattr(fetch.requests, "get", get)

    with pytest.raises(fetch.OpenFdaError) as error:
        fetch.get(fetch.BASE_URL, {})
    assert "could not reach" in str(error.value)
    assert len(calls) == fetch.MAX_ATTEMPTS


def test_a_connection_error_then_success_works(monkeypatch):
    get, calls = fake_get([requests.ConnectionError("dns"), Response(200)])
    monkeypatch.setattr(fetch.requests, "get", get)

    assert fetch.get(fetch.BASE_URL, {}) == BODY
    assert len(calls) == 2


def test_count_reports_reads_the_total(monkeypatch):
    get, _ = fake_get([Response(200)])
    monkeypatch.setattr(fetch.requests, "get", get)
    assert fetch.count_reports("x") == 42


def test_count_reports_returns_zero_on_no_match(monkeypatch):
    get, _ = fake_get([Response(404)])
    monkeypatch.setattr(fetch.requests, "get", get)
    assert fetch.count_reports("x") == 0


def test_the_api_key_is_only_sent_when_there_is_one(monkeypatch):
    get, calls = fake_get([Response(200)])
    monkeypatch.setattr(fetch.requests, "get", get)

    fetch.count_reports("x")
    assert "api_key" not in calls[0]

    fetch.count_reports("x", api_key="secret")
    assert calls[1]["api_key"] == "secret"


def test_the_search_expression_is_uppercased():
    assert fetch.build_search("ibuprofen", "nausea") == (
        'patient.drug.medicinalproduct:"IBUPROFEN"'
        ' AND patient.reaction.reactionmeddrapt:"NAUSEA"'
    )


def test_the_search_expression_drops_the_reaction_when_there_is_none():
    assert fetch.build_search("ibuprofen", None) == 'patient.drug.medicinalproduct:"IBUPROFEN"'
