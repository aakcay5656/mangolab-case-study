"""Where a rate is tied to a date, honestly.

The upstream backfills: ask it about a Saturday and it answers with Friday's
rate, and it says so in its own `date` field. That behaviour is useful — a
customer usually wants the number rather than a refusal — but only if the answer
carries the day it belongs to. So nothing here ever moves a rate onto a
different date; it only reports the two dates side by side.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from fxtool.errors import tool_error
from fxtool.upstream import Upstream
from fxtool.validate import today


@dataclass(frozen=True)
class DatedRate:
    rate: Decimal
    rate_date: date  # the day this rate belongs to, per the upstream
    asked_date: date  # the day the caller asked about

    @property
    def is_from_an_earlier_day(self) -> bool:
        return self.rate_date < self.asked_date


async def dated_rate(
    upstream: Upstream, base: str, target: str, asked: date | None
) -> DatedRate:
    """Fetch a rate and pin it to the day the upstream says it belongs to.

    `asked is None` means the caller wants the latest publication, which is a
    question about today; saying so keeps a Sunday request visibly answered with
    Friday's rate instead of silently.
    """
    asked_date = asked if asked is not None else today()
    quote = await upstream.fetch_quote(base, target, asked)

    if quote.rate_date > asked_date:
        # A rate from after the day in question cannot be the answer to it. This
        # should not happen; if it does, the number is not one we can stand behind.
        raise tool_error(
            "upstream_invalid_response",
            f"The exchange-rate service answered with a rate from {quote.rate_date}, "
            f"which is after the {asked_date} that was asked about.",
        )

    return DatedRate(rate=quote.rate, rate_date=quote.rate_date, asked_date=asked_date)


# Money is rounded to cents at the very end, and half a cent rounds up. Python's
# built-in round() would do neither: it rounds half to even, on a float.
CENTS = Decimal("0.01")


@dataclass(frozen=True)
class Conversion:
    amount: Decimal
    base: str
    target: str
    rate: Decimal
    result: Decimal
    rate_date: date
    asked_date: date


async def convert(
    upstream: Upstream, amount: Decimal, base: str, target: str, asked: date | None
) -> Conversion:
    dated = await dated_rate(upstream, base, target, asked)

    # Decimal all the way through: the rate keeps every digit it was published
    # with, and only the customer-facing total is rounded.
    result = (amount * dated.rate).quantize(CENTS, rounding=ROUND_HALF_UP)

    return Conversion(
        amount=amount,
        base=base,
        target=target,
        rate=dated.rate,
        result=result,
        rate_date=dated.rate_date,
        asked_date=dated.asked_date,
    )
