"""The Frankfurter client.

Two rules live here:

1. The real host appears exactly once in this file, as the default of an
   environment variable. Everything else builds its URL from configuration.
2. Nothing that comes back over the wire is trusted. A rate is only a rate once
   the status, the content type, the shape, and the number itself have all been
   checked. Anything short of that is an error, never a fallback number.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

from fxtool.errors import ToolError, tool_error

DEFAULT_BASE = "https://api.frankfurter.dev"

# The published API is versioned; the configured base is the host root, so the
# version belongs here. (Measured: /v1/latest is 200, /latest is 404.)
API_PREFIX = "v1"

# A tool call sits inside a model's turn while a customer waits, so the budget is
# small and explicit. A client without timeouts is a client that can hang for ever.
TIMEOUT = httpx.Timeout(connect=2.0, read=4.0, write=2.0, pool=2.0)


@dataclass(frozen=True)
class Quote:
    """A rate together with the day it actually belongs to."""

    rate: Decimal
    rate_date: date


def upstream_base() -> str:
    """Read at call time, so tests and reviewers can repoint us without a restart."""
    base = os.environ.get("FX_UPSTREAM_BASE", DEFAULT_BASE).strip().rstrip("/")
    if base.endswith(f"/{API_PREFIX}"):
        # Already versioned; adding it twice would 404 in a way that looks like
        # "no rate for that date", which is the worst kind of misconfiguration.
        return base
    return f"{base}/{API_PREFIX}"


class Upstream:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def fetch_quote(self, base: str, target: str, on: date | None) -> Quote:
        """Ask for one rate. Returns the rate *and the date the upstream says it is from*."""
        path = on.isoformat() if on else "latest"
        try:
            payload = await self._get(path, {"base": base, "symbols": target})
        except ToolError as exc:
            # A 404 here means one of two very different things to a customer:
            # "nobody publishes that currency" or "nothing was published that day".
            if exc.code == "no_rate_for_date":
                await self._raise_if_currency_unknown(base, target)
            raise

        # Deliberately not using the upstream's own `amount` parameter: we want
        # the bare rate so the arithmetic stays ours, in Decimal.
        rates = payload.get("rates")
        if not isinstance(rates, dict) or target not in rates:
            await self._raise_if_currency_unknown(base, target)
            raise self._no_rate_error(base, target, on)

        return Quote(rate=self._as_rate(rates[target]), rate_date=self._as_date(payload.get("date")))

    async def _raise_if_currency_unknown(self, base: str, target: str) -> None:
        """Turn a bare 404 into the specific answer, when we can confirm it."""
        try:
            known = await self.known_currencies()
        except ToolError:
            # We could not check. The 404 we already have is still true, so we
            # report that rather than guess at a cause.
            return

        missing = [code for code in (base, target) if code not in known]
        if missing:
            raise tool_error(
                "unknown_currency",
                f"{' and '.join(missing)} is not a currency the ECB publishes."
                if len(missing) == 1
                else f"{' and '.join(missing)} are not currencies the ECB publishes.",
            )

    async def known_currencies(self) -> set[str]:
        payload = await self._get("currencies", None)
        return {code.upper() for code in payload if isinstance(code, str)}

    async def _get(self, path: str, params: dict[str, str] | None) -> dict:
        url = f"{upstream_base()}/{path}"
        try:
            response = await self._client.get(url, params=params, timeout=TIMEOUT)
        except httpx.TimeoutException:
            raise tool_error(
                "upstream_timeout", "The exchange-rate service did not answer in time."
            ) from None
        except httpx.HTTPError:
            raise tool_error(
                "upstream_unavailable", "The exchange-rate service could not be reached."
            ) from None

        self._check_status(response, path)

        try:
            payload = response.json()
        except ValueError:
            raise tool_error(
                "upstream_invalid_response",
                "The exchange-rate service returned something that is not JSON.",
            ) from None

        if not isinstance(payload, dict):
            raise tool_error(
                "upstream_invalid_response",
                "The exchange-rate service returned an unexpected document.",
            )
        return payload

    def _check_status(self, response: httpx.Response, path: str) -> None:
        if response.status_code == 200:
            return
        if response.status_code == 404:
            raise tool_error("no_rate_for_date", f"The exchange-rate service has nothing for {path}.")
        if response.status_code >= 500:
            raise tool_error(
                "upstream_unavailable",
                f"The exchange-rate service failed with status {response.status_code}.",
            )
        raise tool_error(
            "upstream_invalid_response",
            f"The exchange-rate service rejected our request with status {response.status_code}.",
        )

    def _no_rate_error(self, base: str, target: str, on: date | None) -> Exception:
        when = f"for {on}" if on else "for the latest publication"
        return tool_error(
            "no_rate_for_date",
            f"The exchange-rate service published no {base}/{target} rate {when}.",
        )

    @staticmethod
    def _as_rate(raw: object) -> Decimal:
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
            raise tool_error("upstream_invalid_response", "The rate we were given is not a number.")
        try:
            rate = Decimal(str(raw))
        except InvalidOperation:
            raise tool_error(
                "upstream_invalid_response", "The rate we were given is not a number."
            ) from None
        if not rate.is_finite() or rate <= 0:
            # A zero or negative rate would multiply a customer's money into a
            # number that looks answered and is nonsense.
            raise tool_error("upstream_invalid_response", "The rate we were given is not usable.")
        return rate

    @staticmethod
    def _as_date(raw: object) -> date:
        """The upstream tells us which day its rates are from. Read it; never assume it."""
        if not isinstance(raw, str):
            raise tool_error(
                "upstream_invalid_response",
                "The exchange-rate service did not say which day the rate is from.",
            )
        try:
            return date.fromisoformat(raw)
        except ValueError:
            raise tool_error(
                "upstream_invalid_response",
                f"The exchange-rate service reported an unreadable date: {raw!r}.",
            ) from None
