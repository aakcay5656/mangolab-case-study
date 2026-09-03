"""FX conversion tool for an agent runtime.

One endpoint, GET /tools/convert, backed by the ECB rates published at
frankfurter.dev. The upstream base URL is configuration, not code.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal

import httpx
from fastapi import FastAPI, Query, Request

from fxtool.cache import CachingUpstream
from fxtool.errors import install_error_handlers
from fxtool.service import Conversion, convert
from fxtool.upstream import TIMEOUT, Upstream
from fxtool.validate import parse_amount, parse_date, parse_pair

SOURCE = "ECB via frankfurter.dev"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """One connection pool for the process, closed on the way out."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        app.state.upstream = CachingUpstream(Upstream(client))
        yield


app = FastAPI(title="fx-tool", version="1.0", lifespan=lifespan)
install_error_handlers(app)


def _number(value: Decimal) -> float | int:
    """Render a Decimal as a JSON number.

    The arithmetic is done in Decimal; this is only the last step out of the
    door, where the response format asks for numbers rather than strings.
    """
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def _payload(conversion: Conversion) -> dict:
    return {
        "amount": _number(conversion.amount),
        "from": conversion.base,
        "to": conversion.target,
        "rate": _number(conversion.rate),
        "result": _number(conversion.result),
        "rate_date": conversion.rate_date.isoformat(),
        "asked_date": conversion.asked_date.isoformat(),
        "source": SOURCE,
    }


@app.get("/tools/convert")
async def convert_endpoint(
    request: Request,
    amount: str = Query(..., description="How much to convert, e.g. 250"),
    from_: str = Query(..., alias="from", description="Source currency code, e.g. EUR"),
    to: str = Query(..., description="Target currency code, e.g. TRY"),
    on: str | None = Query(
        None, alias="date", description="ISO date; omitted means the latest publication"
    ),
) -> dict:
    """Convert an amount between two currencies at the ECB's published rate.

    The parameters are taken as text and parsed here so that a bad amount or a
    bad date produces our own named error rather than a framework message, and
    so that the amount never passes through a float on its way in.
    """
    parsed_amount = parse_amount(amount)
    base, target = parse_pair(from_, to)
    asked = parse_date(on)

    conversion = await convert(request.app.state.upstream, parsed_amount, base, target, asked)
    return _payload(conversion)


@app.get("/health")
async def health() -> dict:
    return {"ok": True}
