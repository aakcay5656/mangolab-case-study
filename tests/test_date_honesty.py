"""The one thing this service must never get wrong: which day a rate is from."""

import asyncio
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest

from fxtool.errors import ToolError
from fxtool.service import dated_rate
from fxtool.upstream import Upstream
from fxtool.validate import today


@pytest.fixture(autouse=True)
def fake_base(monkeypatch):
    monkeypatch.setenv("FX_UPSTREAM_BASE", "http://fake.upstream.test")


def upstream_answering(rate_date: str, rate: float = 47.1234) -> Upstream:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"date": rate_date, "rates": {"TRY": rate}})

    return Upstream(httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def resolve(upstream, asked):
    return asyncio.run(dated_rate(upstream, "EUR", "TRY", asked))


def test_a_weekend_is_answered_with_the_previous_business_day_and_both_dates_show():
    saturday = date(2026, 8, 29)
    friday = date(2026, 8, 28)

    result = resolve(upstream_answering("2026-08-28"), saturday)

    assert result.rate == Decimal("47.1234")
    assert result.rate_date == friday, "the rate must keep the day the upstream gave it"
    assert result.asked_date == saturday, "and the caller's question must survive too"
    assert result.is_from_an_earlier_day


def test_a_business_day_answers_with_its_own_date():
    friday = date(2026, 8, 28)

    result = resolve(upstream_answering("2026-08-28"), friday)

    assert result.rate_date == result.asked_date == friday
    assert not result.is_from_an_earlier_day


def test_a_long_holiday_gap_is_reported_not_hidden():
    # Nothing caps how stale a backfilled rate may be; the answer just has to
    # say which day it is from, so the model can tell the customer.
    result = resolve(upstream_answering("2026-12-24"), date(2026, 12, 28))

    assert result.rate_date == date(2026, 12, 24)
    assert result.asked_date == date(2026, 12, 28)
    assert result.is_from_an_earlier_day


def test_no_date_asked_means_today_so_a_stale_latest_is_still_visible():
    yesterday = today() - timedelta(days=1)

    result = resolve(upstream_answering(str(yesterday)), None)

    assert result.asked_date == today()
    assert result.rate_date == yesterday
    assert result.is_from_an_earlier_day


def test_a_rate_from_after_the_day_asked_about_is_refused():
    with pytest.raises(ToolError) as excinfo:
        resolve(upstream_answering("2026-08-30"), date(2026, 8, 28))

    assert excinfo.value.code == "upstream_invalid_response"
    assert "2026-08-30" in excinfo.value.message
