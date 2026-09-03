"""The upstream client, exercised against a fake that never touches a socket.

Every one of these is a way the real service can lie to us or fall over. The
assertion is always the same shape: we get a named error, never a number.
"""

import asyncio
import json

import httpx
import pytest

from fxtool.errors import ToolError
from fxtool.upstream import Upstream, upstream_base

RATES_BODY = {"amount": 1.0, "base": "EUR", "date": "2026-08-28", "rates": {"TRY": 47.1234}}
CURRENCIES_BODY = {"EUR": "Euro", "TRY": "Turkish Lira", "USD": "US Dollar"}


def run(coro):
    return asyncio.run(coro)


def upstream_of(handler) -> tuple[Upstream, list[httpx.Request]]:
    """An Upstream wired to a fake, plus the list of requests it received."""
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(record))
    return Upstream(client), seen


def responder(body, status=200, *, text=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/currencies"):
            return httpx.Response(200, json=CURRENCIES_BODY)
        if text is not None:
            return httpx.Response(status, text=text)
        return httpx.Response(status, json=body)

    return handler


@pytest.fixture(autouse=True)
def fake_base(monkeypatch):
    monkeypatch.setenv("FX_UPSTREAM_BASE", "http://fake.upstream.test")


# --- configuration -----------------------------------------------------------

def test_the_upstream_host_is_configuration(monkeypatch):
    monkeypatch.setenv("FX_UPSTREAM_BASE", "http://127.0.0.1:9999")
    assert upstream_base() == "http://127.0.0.1:9999/v1"


def test_a_base_that_already_carries_the_version_is_not_versioned_twice(monkeypatch):
    monkeypatch.setenv("FX_UPSTREAM_BASE", "http://127.0.0.1:9999/v1/")
    assert upstream_base() == "http://127.0.0.1:9999/v1"


def test_requests_go_where_the_environment_points(monkeypatch):
    from datetime import date

    upstream, seen = upstream_of(responder(RATES_BODY))
    run(upstream.fetch_quote("EUR", "TRY", date(2026, 8, 28)))

    url = seen[0].url
    assert str(url).startswith("http://fake.upstream.test/v1/2026-08-28")
    assert dict(url.params) == {"base": "EUR", "symbols": "TRY"}
    # We ask for the bare rate: the multiplication is ours to do, in Decimal.
    assert "amount" not in url.params


def test_no_date_asks_for_the_latest_publication():
    upstream, seen = upstream_of(responder(RATES_BODY))
    run(upstream.fetch_quote("EUR", "TRY", None))

    assert seen[0].url.path.endswith("/v1/latest")


# --- the happy path ----------------------------------------------------------

def test_the_rate_and_its_date_both_come_from_the_payload():
    from datetime import date
    from decimal import Decimal

    upstream, _ = upstream_of(responder(RATES_BODY))
    quote = run(upstream.fetch_quote("EUR", "TRY", date(2026, 8, 29)))

    assert quote.rate == Decimal("47.1234")
    assert quote.rate_date == date(2026, 8, 28)  # what the upstream said, not what we asked


def test_the_rate_keeps_every_digit_it_arrived_with():
    from decimal import Decimal

    body = dict(RATES_BODY, rates={"TRY": 47.123456789})
    upstream, _ = upstream_of(responder(body))

    assert run(upstream.fetch_quote("EUR", "TRY", None)).rate == Decimal("47.123456789")


# --- the ways it can fail ----------------------------------------------------

def raises_code(coro) -> str:
    with pytest.raises(ToolError) as excinfo:
        run(coro)
    return excinfo.value.code


def test_a_404_for_a_real_pair_is_a_missing_rate_not_a_missing_currency():
    upstream, _ = upstream_of(responder(None, 404))
    assert raises_code(upstream.fetch_quote("EUR", "TRY", None)) == "no_rate_for_date"


def test_a_404_for_a_currency_nobody_publishes_says_so():
    upstream, _ = upstream_of(responder(None, 404))
    assert raises_code(upstream.fetch_quote("EUR", "XXX", None)) == "unknown_currency"


def test_when_the_currency_list_is_unreachable_the_404_stands_as_reported():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/currencies"):
            return httpx.Response(500)
        return httpx.Response(404)

    upstream, _ = upstream_of(handler)
    assert raises_code(upstream.fetch_quote("EUR", "XXX", None)) == "no_rate_for_date"


def test_a_payload_without_our_currency_is_not_silently_accepted():
    upstream, _ = upstream_of(responder(dict(RATES_BODY, rates={"USD": 1.1})))
    assert raises_code(upstream.fetch_quote("EUR", "TRY", None)) == "no_rate_for_date"


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_an_upstream_failure_is_never_a_number(status):
    upstream, _ = upstream_of(responder(None, status))
    assert raises_code(upstream.fetch_quote("EUR", "TRY", None)) == "upstream_unavailable"


def test_an_upstream_that_rejects_our_request_is_reported_as_such():
    upstream, _ = upstream_of(responder({"message": "bad currency pair"}, 422))
    assert raises_code(upstream.fetch_quote("EUR", "TRY", None)) == "upstream_invalid_response"


def test_html_instead_of_json_is_an_error_not_a_crash():
    upstream, _ = upstream_of(responder(None, 200, text="<html>502 Bad Gateway</html>"))
    assert raises_code(upstream.fetch_quote("EUR", "TRY", None)) == "upstream_invalid_response"


def test_a_json_document_of_the_wrong_shape_is_refused():
    def handler(request):
        return httpx.Response(200, content=json.dumps([1, 2, 3]), headers={"content-type": "application/json"})

    upstream, _ = upstream_of(handler)
    assert raises_code(upstream.fetch_quote("EUR", "TRY", None)) == "upstream_invalid_response"


def test_a_payload_with_no_date_is_refused_even_though_it_has_a_rate():
    body = {"rates": {"TRY": 47.1234}}
    upstream, _ = upstream_of(responder(body))
    assert raises_code(upstream.fetch_quote("EUR", "TRY", None)) == "upstream_invalid_response"


@pytest.mark.parametrize("bad_date", ["not-a-date", "28/08/2026", 20260828, None])
def test_an_unreadable_date_is_refused(bad_date):
    upstream, _ = upstream_of(responder(dict(RATES_BODY, date=bad_date)))
    assert raises_code(upstream.fetch_quote("EUR", "TRY", None)) == "upstream_invalid_response"


@pytest.mark.parametrize("bad_rate", [0, -1.5, "abc", None, True, [47.1]])
def test_a_rate_that_is_not_a_usable_number_is_refused(bad_rate):
    upstream, _ = upstream_of(responder(dict(RATES_BODY, rates={"TRY": bad_rate})))
    assert raises_code(upstream.fetch_quote("EUR", "TRY", None)) == "upstream_invalid_response"


def test_a_slow_upstream_times_out_instead_of_hanging():
    def handler(request):
        raise httpx.ReadTimeout("too slow", request=request)

    upstream, _ = upstream_of(handler)
    assert raises_code(upstream.fetch_quote("EUR", "TRY", None)) == "upstream_timeout"


def test_an_unreachable_upstream_is_reported_not_guessed():
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    upstream, _ = upstream_of(handler)
    assert raises_code(upstream.fetch_quote("EUR", "TRY", None)) == "upstream_unavailable"
