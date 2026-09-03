"""What the cache must remember, and what it must never confuse.

The dangerous failure is not a stale rate; it is a rate filed under the wrong
question. Most of these tests are about the key.
"""

import asyncio
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest

from fxtool.cache import MOVING_TTL_SECONDS, SETTLED_TTL_SECONDS, CachingUpstream, TtlCache
from fxtool.errors import ToolError
from fxtool.upstream import Upstream
from fxtool.validate import today

SETTLED = date(2026, 8, 28)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture(autouse=True)
def fake_base(monkeypatch):
    monkeypatch.setenv("FX_UPSTREAM_BASE", "http://fake.upstream.test")


def caching_upstream(clock=None, *, status=200):
    """A caching upstream over a fake that records every request it receives."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/currencies"):
            return httpx.Response(200, json={"EUR": "Euro", "TRY": "Turkish Lira"})
        if status != 200:
            return httpx.Response(status)
        # Answer as the real upstream does: the date it used, and the symbol asked for.
        asked_path = request.url.path.rsplit("/", 1)[-1]
        rate_date = str(today()) if asked_path == "latest" else asked_path
        symbol = request.url.params["symbols"]
        return httpx.Response(200, json={"date": rate_date, "rates": {symbol: 47.1234}})

    inner = Upstream(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return CachingUpstream(inner, clock or Clock()), seen


def ask(upstream, base="EUR", target="TRY", on=SETTLED):
    return asyncio.run(upstream.fetch_quote(base, target, on))


# --- the point of the cache --------------------------------------------------

def test_the_same_question_twice_asks_the_upstream_once():
    upstream, seen = caching_upstream()

    first = ask(upstream)
    second = ask(upstream)

    assert len(seen) == 1
    assert first == second


# --- the key -----------------------------------------------------------------

def test_a_different_date_is_a_different_question():
    upstream, seen = caching_upstream()

    ask(upstream, on=date(2026, 8, 28))
    ask(upstream, on=date(2026, 3, 12))

    assert len(seen) == 2, "a cache keyed without the date answers March with August"


def test_the_latest_and_a_specific_date_are_different_questions():
    upstream, seen = caching_upstream()

    ask(upstream, on=None)
    ask(upstream, on=SETTLED)

    assert len(seen) == 2


def test_a_different_pair_is_a_different_question():
    upstream, seen = caching_upstream()

    ask(upstream, target="TRY")
    ask(upstream, target="USD")

    assert len(seen) == 2


def test_the_direction_of_the_pair_is_part_of_the_question():
    upstream, seen = caching_upstream()

    ask(upstream, base="EUR", target="TRY")
    ask(upstream, base="TRY", target="EUR")

    assert len(seen) == 2


def test_the_cached_answer_is_the_answer_and_not_a_reused_number():
    upstream, _ = caching_upstream()

    quote = ask(upstream, on=SETTLED)
    again = ask(upstream, on=SETTLED)

    assert again.rate == Decimal("47.1234")
    assert again.rate_date == quote.rate_date == SETTLED


# --- lifetimes ---------------------------------------------------------------

def test_the_latest_rate_is_asked_again_once_it_has_had_its_minute():
    clock = Clock()
    upstream, seen = caching_upstream(clock)

    ask(upstream, on=None)
    clock.advance(MOVING_TTL_SECONDS + 1)
    ask(upstream, on=None)

    assert len(seen) == 2


def test_todays_rate_is_treated_as_still_moving():
    clock = Clock()
    upstream, seen = caching_upstream(clock)

    ask(upstream, on=today())
    clock.advance(MOVING_TTL_SECONDS + 1)
    ask(upstream, on=today())

    assert len(seen) == 2, "today is not settled until the ECB has published"


def test_a_settled_day_is_not_asked_again_a_minute_later():
    clock = Clock()
    upstream, seen = caching_upstream(clock)

    ask(upstream, on=SETTLED)
    clock.advance(MOVING_TTL_SECONDS + 1)
    ask(upstream, on=SETTLED)

    assert len(seen) == 1, "the ECB does not revise a day that has already passed"


def test_even_a_settled_day_is_eventually_asked_again():
    clock = Clock()
    upstream, seen = caching_upstream(clock)

    ask(upstream, on=SETTLED)
    clock.advance(SETTLED_TTL_SECONDS + 1)
    ask(upstream, on=SETTLED)

    assert len(seen) == 2


# --- what must never be remembered -------------------------------------------

def test_a_failure_is_not_remembered():
    upstream, seen = caching_upstream(status=500)

    for _ in range(3):
        with pytest.raises(ToolError):
            ask(upstream)

    assert len(seen) == 3, "a minute of upstream trouble must not become a minute of it"


def test_the_currency_list_is_only_fetched_once():
    upstream, seen = caching_upstream()

    asyncio.run(upstream.known_currencies())
    asyncio.run(upstream.known_currencies())

    assert len([r for r in seen if r.url.path.endswith("/currencies")]) == 1


# --- the cache itself --------------------------------------------------------

def test_entries_disappear_when_they_expire():
    clock = Clock()
    cache: TtlCache[str] = TtlCache(clock)

    cache.set("k", "v", ttl=10)
    assert cache.get("k") == "v"

    clock.advance(11)
    assert cache.get("k") is None


def test_the_cache_does_not_grow_without_limit():
    from fxtool.cache import MAX_ENTRIES

    cache: TtlCache[int] = TtlCache(Clock())
    for index in range(MAX_ENTRIES * 2):
        cache.set(index, index, ttl=3600)

    assert len(cache) <= MAX_ENTRIES
