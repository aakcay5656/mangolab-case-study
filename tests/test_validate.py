"""Input rules, tested without a socket in sight."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from fxtool.errors import ToolError
from fxtool.validate import (
    SERIES_START,
    parse_amount,
    parse_currency,
    parse_date,
    parse_pair,
    today,
)


def code_of(excinfo) -> str:
    return excinfo.value.code


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("250", Decimal("250")),
        ("250.5", Decimal("250.5")),
        (" 250 ", Decimal("250")),
        ("0.0000000001", Decimal("0.0000000001")),  # ten decimals: kept, not truncated
        ("1e3", Decimal("1000")),
    ],
)
def test_valid_amounts_are_kept_exactly(raw, expected):
    assert parse_amount(raw) == expected


@pytest.mark.parametrize("raw", ["0", "-1", "-0.01", "abc", "", "NaN", "Infinity", "1e13"])
def test_amounts_that_cannot_mean_money_are_refused(raw):
    with pytest.raises(ToolError) as excinfo:
        parse_amount(raw)
    assert code_of(excinfo) == "invalid_amount"


def test_amount_is_never_a_float():
    # 0.1 + 0.2 == 0.30000000000000004 as a float; as a Decimal it is exact.
    assert parse_amount("0.1") + parse_amount("0.2") == Decimal("0.3")


@pytest.mark.parametrize("raw, expected", [("EUR", "EUR"), ("try", "TRY"), (" usd ", "USD")])
def test_currency_codes_are_normalised(raw, expected):
    assert parse_currency(raw, "from") == expected


@pytest.mark.parametrize("raw", ["EU", "EUROS", "E1R", "", "€"])
def test_malformed_currency_codes_are_refused(raw):
    with pytest.raises(ToolError) as excinfo:
        parse_currency(raw, "from")
    assert code_of(excinfo) == "invalid_currency"


def test_a_pair_of_the_same_currency_is_refused():
    with pytest.raises(ToolError) as excinfo:
        parse_pair("EUR", "eur")
    assert code_of(excinfo) == "same_currency"


@pytest.mark.parametrize("raw", [None, "", "  "])
def test_no_date_means_the_latest_published_rate(raw):
    assert parse_date(raw) is None


def test_a_valid_past_date_is_accepted():
    assert parse_date("2026-08-28") == date(2026, 8, 28)


@pytest.mark.parametrize("raw", ["28-08-2026", "2026/08/28", "20260828", "2026-13-45", "yesterday"])
def test_unparseable_dates_are_refused(raw):
    with pytest.raises(ToolError) as excinfo:
        parse_date(raw)
    assert code_of(excinfo) == "invalid_date"


def test_tomorrow_is_refused_before_we_call_anybody():
    with pytest.raises(ToolError) as excinfo:
        parse_date(str(today() + timedelta(days=1)))
    assert code_of(excinfo) == "date_in_future"


def test_today_is_allowed():
    assert parse_date(str(today())) == today()


def test_the_day_before_the_series_starts_is_refused():
    with pytest.raises(ToolError) as excinfo:
        parse_date(str(SERIES_START - timedelta(days=1)))
    assert code_of(excinfo) == "date_before_series"


def test_the_first_day_of_the_series_is_allowed():
    assert parse_date(str(SERIES_START)) == SERIES_START


def test_the_future_date_message_names_the_publisher_calendar():
    # "Today" is Frankfurt's today. At 00:30 in Istanbul it is still yesterday
    # there, and a caller asking about their own date should be told why.
    with pytest.raises(ToolError) as excinfo:
        parse_date(str(today() + timedelta(days=1)))

    assert str(today()) in excinfo.value.message
    assert "Frankfurt" in excinfo.value.message
