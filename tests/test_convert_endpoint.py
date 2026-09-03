"""The endpoint as a caller sees it, with a fake upstream behind it."""

from contextlib import contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient

from fxtool.main import app
from fxtool.upstream import Upstream

BRIEF_QUERY = {"amount": "250", "from": "EUR", "to": "TRY", "date": "2026-08-28"}


@pytest.fixture(autouse=True)
def fake_base(monkeypatch):
    monkeypatch.setenv("FX_UPSTREAM_BASE", "http://fake.upstream.test")


@contextmanager
def service(handler=None, *, rate=47.1234, rate_date="2026-08-28"):
    """The real app, with the upstream swapped for a fake. No socket is opened."""
    calls: list[httpx.Request] = []

    def default(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"date": rate_date, "rates": {"TRY": rate}})

    def record(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return (handler or default)(request)

    with TestClient(app, raise_server_exceptions=False) as client:
        app.state.upstream = Upstream(httpx.AsyncClient(transport=httpx.MockTransport(record)))
        yield client, calls


def test_the_query_from_the_brief_answers_with_the_body_from_the_brief():
    with service() as (client, _):
        response = client.get("/tools/convert", params=BRIEF_QUERY)

    assert response.status_code == 200
    assert response.json() == {
        "amount": 250,
        "from": "EUR",
        "to": "TRY",
        "rate": 47.1234,
        "result": 11780.85,
        "rate_date": "2026-08-28",
        "asked_date": "2026-08-28",
        "source": "ECB via frankfurter.dev",
    }


def test_the_rate_is_passed_through_at_full_precision():
    with service(rate=47.123456789) as (client, _):
        body = client.get("/tools/convert", params=BRIEF_QUERY).json()

    # Rounding the rate to two places would cost about 45 kurus on 250 EUR, and
    # the answer would still look perfectly reasonable.
    assert body["rate"] == 47.123456789
    assert body["result"] == 11780.86


def test_half_a_cent_rounds_up_and_not_to_even():
    with service(rate=2.005) as (client, _):
        body = client.get("/tools/convert", params={**BRIEF_QUERY, "amount": "1"}).json()

    assert body["result"] == 2.01  # round(2.005, 2) would answer 2.0


def test_ten_decimal_places_in_the_amount_are_used_not_truncated():
    with service(rate=2) as (client, _):
        body = client.get("/tools/convert", params={**BRIEF_QUERY, "amount": "1.0000000001"}).json()

    assert body["result"] == 2.0


def test_a_saturday_is_answered_with_fridays_rate_and_says_so():
    with service(rate_date="2026-08-28") as (client, _):
        body = client.get("/tools/convert", params={**BRIEF_QUERY, "date": "2026-08-29"}).json()

    assert body["rate_date"] == "2026-08-28"
    assert body["asked_date"] == "2026-08-29"


def test_omitting_the_date_still_reports_which_day_the_rate_is_from():
    from fxtool.validate import today

    with service(rate_date="2026-08-28") as (client, _):
        body = client.get("/tools/convert", params={"amount": "250", "from": "EUR", "to": "TRY"}).json()

    assert body["rate_date"] == "2026-08-28"
    assert body["asked_date"] == str(today())


def test_lowercase_currency_codes_are_accepted_and_echoed_uppercase():
    with service() as (client, _):
        body = client.get("/tools/convert", params={**BRIEF_QUERY, "from": "eur", "to": "try"}).json()

    assert (body["from"], body["to"]) == ("EUR", "TRY")


# --- failures never come back as numbers -------------------------------------

def failing_upstream(status: int):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status)

    return handler


def test_an_upstream_failure_returns_an_error_and_no_rate_at_all():
    with service(failing_upstream(500)) as (client, _):
        response = client.get("/tools/convert", params=BRIEF_QUERY)

    assert response.status_code == 502
    assert response.json() == {
        "error": "upstream_unavailable",
        "message": "The exchange-rate service failed with status 500.",
    }
    assert "rate" not in response.json()


@pytest.mark.parametrize(
    "params, code",
    [
        ({"amount": "0"}, "invalid_amount"),
        ({"amount": "-5"}, "invalid_amount"),
        ({"amount": "abc"}, "invalid_amount"),
        ({"from": "EUR", "to": "EUR"}, "same_currency"),
        ({"from": "EUROS"}, "invalid_currency"),
        ({"date": "29-08-2026"}, "invalid_date"),
        ({"date": "2999-01-01"}, "date_in_future"),
        ({"date": "1998-12-31"}, "date_before_series"),
    ],
)
def test_a_request_we_cannot_answer_honestly_never_reaches_the_upstream(params, code):
    with service() as (client, calls):
        response = client.get("/tools/convert", params={**BRIEF_QUERY, **params})

    assert response.json()["error"] == code
    assert response.status_code >= 400
    assert calls == [], "we asked the upstream about a request we had already refused"


@pytest.mark.parametrize("missing", ["amount", "from", "to"])
def test_a_missing_required_parameter_is_named_in_the_error(missing):
    params = {key: value for key, value in BRIEF_QUERY.items() if key != missing}

    with service() as (client, _):
        response = client.get("/tools/convert", params=params)

    assert response.status_code == 422
    assert f"'{missing}'" in response.json()["message"]
