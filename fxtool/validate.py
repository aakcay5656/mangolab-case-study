"""Everything we can reject without asking anybody.

A request that cannot produce an honest number is refused here, before a socket
is opened: it is cheaper, and it keeps the upstream client free of guesswork.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from fxtool.errors import tool_error

# The ECB's euro reference rates start here; nothing exists before it.
SERIES_START = date(1999, 1, 4)

# The rates are published in Frankfurt, so "today" is Frankfurt's today. Using
# the server's local calendar would refuse a perfectly valid date whenever the
# machine happens to sit in a timezone ahead of the publisher.
PUBLISHER_TZ = ZoneInfo("Europe/Berlin")

# Above this an "amount" is not a customer's money any more, it is a typo or an
# overflow probe. Below zero it is not an amount at all.
MAX_AMOUNT = Decimal("1e12")

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def today() -> date:
    return datetime.now(PUBLISHER_TZ).date()


def parse_amount(raw: str) -> Decimal:
    """Parse the amount exactly, as a decimal — never as a float.

    Any number of decimal places is accepted and kept for the multiplication;
    only the final result is rounded. Rejecting a customer's real amount because
    it has ten decimals would be unhelpful, and silently truncating it would be
    a lie about their money.
    """
    text = raw.strip()
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise tool_error("invalid_amount", f"'{raw}' is not a number.") from None

    if not amount.is_finite():
        raise tool_error("invalid_amount", "The amount must be a finite number.")
    if amount <= 0:
        raise tool_error("invalid_amount", "The amount must be greater than zero.")
    if amount > MAX_AMOUNT:
        raise tool_error("invalid_amount", f"The amount must not exceed {MAX_AMOUNT:,.0f}.")

    return amount


def parse_currency(raw: str, field: str) -> str:
    """Check the shape of a currency code. Whether it exists is the upstream's word."""
    code = raw.strip().upper()
    if not _CURRENCY_RE.match(code):
        raise tool_error(
            "invalid_currency",
            f"'{raw}' is not a currency code; '{field}' takes three letters, such as EUR.",
        )
    return code


def parse_pair(raw_from: str, raw_to: str) -> tuple[str, str]:
    base = parse_currency(raw_from, "from")
    target = parse_currency(raw_to, "to")
    if base == target:
        raise tool_error(
            "same_currency",
            f"'from' and 'to' are both {base}; there is no exchange rate to quote.",
        )
    return base, target


def parse_date(raw: str | None) -> date | None:
    """None means "whatever the ECB published most recently"."""
    if raw is None or raw.strip() == "":
        return None

    text = raw.strip()
    if not _ISO_DATE_RE.match(text):
        raise tool_error("invalid_date", f"'{raw}' is not a date; use YYYY-MM-DD.")
    try:
        asked = date.fromisoformat(text)
    except ValueError:
        raise tool_error("invalid_date", f"'{raw}' is not a real date.") from None

    if asked > today():
        # Named explicitly, because a caller in a timezone ahead of Frankfurt can
        # be asking about their own today and deserves to know why it is refused.
        raise tool_error(
            "date_in_future",
            f"{asked} is past the last day the ECB could have published: "
            f"it is still {today()} in Frankfurt.",
        )
    if asked < SERIES_START:
        raise tool_error(
            "date_before_series",
            f"{asked} is before the ECB series begins on {SERIES_START}.",
        )

    return asked
