"""A repeat of the same question should not re-ask the upstream.

The whole risk of caching an exchange rate is in the key. A key that forgets the
date will happily answer a question about March with a rate from August, and it
will look completely healthy while it does it — so the date is part of the key,
and the tests say so out loud.

Two lifetimes, because the two kinds of question are different:

* a *past* day is settled; the ECB does not revise it, so it is held for hours;
* *today* and *latest* are still moving — nothing is published until the
  afternoon — so they are held for a minute and asked again.

Failures are never cached. A rate we could not fetch is not an answer worth
keeping, and a minute of upstream trouble should not become a minute of lying.
"""

from __future__ import annotations

import time
from datetime import date
from typing import Callable, Generic, Hashable, TypeVar

from fxtool.upstream import Quote, RateSource
from fxtool.validate import today

# "latest" and today move; everything older does not.
MOVING_TTL_SECONDS = 60.0
SETTLED_TTL_SECONDS = 6 * 60 * 60.0
CURRENCIES_TTL_SECONDS = 24 * 60 * 60.0

# A tool that is asked about many pairs should not grow without limit.
MAX_ENTRIES = 512

V = TypeVar("V")


class TtlCache(Generic[V]):
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._entries: dict[Hashable, tuple[float, V]] = {}

    def get(self, key: Hashable) -> V | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= self._clock():
            del self._entries[key]
            return None
        return value

    def set(self, key: Hashable, value: V, ttl: float) -> None:
        self._entries[key] = (self._clock() + ttl, value)
        self._evict()

    def _evict(self) -> None:
        now = self._clock()
        for key in [k for k, (expires_at, _) in self._entries.items() if expires_at <= now]:
            del self._entries[key]
        while len(self._entries) > MAX_ENTRIES:
            self._entries.pop(next(iter(self._entries)))

    def __len__(self) -> int:
        return len(self._entries)


class CachingUpstream:
    """An Upstream that remembers, wrapped around one that asks."""

    def __init__(self, inner: RateSource, clock: Callable[[], float] = time.monotonic) -> None:
        self._inner = inner
        self._quotes: TtlCache[Quote] = TtlCache(clock)
        self._currencies: TtlCache[set[str]] = TtlCache(clock)

    async def fetch_quote(self, base: str, target: str, on: date | None) -> Quote:
        # The date is in the key. Removing it is the bug this cache exists to avoid.
        key = (base, target, on.isoformat() if on else "latest")

        cached = self._quotes.get(key)
        if cached is not None:
            return cached

        quote = await self._inner.fetch_quote(base, target, on)
        self._quotes.set(key, quote, self._ttl_for(on))
        return quote

    async def known_currencies(self) -> set[str]:
        cached = self._currencies.get("currencies")
        if cached is not None:
            return cached

        currencies = await self._inner.known_currencies()
        self._currencies.set("currencies", currencies, CURRENCIES_TTL_SECONDS)
        return currencies

    @staticmethod
    def _ttl_for(on: date | None) -> float:
        if on is None or on >= today():
            return MOVING_TTL_SECONDS
        return SETTLED_TTL_SECONDS
