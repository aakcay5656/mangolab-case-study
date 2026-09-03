# fx-tool

One endpoint an agent can call as a tool, over the ECB rates published at
frankfurter.dev.

The rule the whole thing is built around: **a wrong number is worse than no
number.** A rate is never invented, and it is never presented as belonging to a
day it does not belong to. When the ECB published nothing for the day asked, the
answer carries both dates so the model can tell the customer which day the
number is from.

## Run

```bash
./run.sh
curl "http://localhost:8080/tools/convert?amount=250&from=EUR&to=TRY&date=2026-08-28"
```

| variable | default | |
|---|---|---|
| `PORT` | `8080` | |
| `FX_UPSTREAM_BASE` | `https://api.frankfurter.dev` | host root; the service appends `/v1` (measured: `/v1/latest` answers, `/latest` is a 404). A base that already ends in `/v1` is not versioned twice. |

The host appears in the code exactly once, as that default —
`tests/test_no_hardcoded_host.py` fails the build if it appears anywhere else.

## Test

```bash
./test.sh
```

129 tests, no network: `tests/conftest.py` replaces the socket for the whole
suite, so any connection off loopback fails the test that made it. `./test.sh`
also defaults `FX_UPSTREAM_BASE` to a closed port, and
`tests/test_no_upstream.py` opens a real socket to a dead local port to prove
the endpoint answers 502 rather than a zero.

## The response

```json
{
  "amount": 250, "from": "EUR", "to": "TRY",
  "rate": 47.1234, "result": 11780.85,
  "rate_date": "2026-08-28", "asked_date": "2026-08-28",
  "source": "ECB via frankfurter.dev"
}
```

`rate_date` is the day the rate belongs to, read from the upstream's own `date`
field. `asked_date` is the day the caller asked about. **When they differ, the
rate is older than the question** — that is the visible signal, and it is the
only fallback this service does.

Every failure, without exception:

```json
{ "error": "upstream_unavailable", "message": "The exchange-rate service could not be reached." }
```

## What it does in each case

| situation | answer |
|---|---|
| weekend or holiday — nothing published that day | **200** with the last published rate, `rate_date` < `asked_date`. No cap on the gap: 28 Dec can answer with 24 Dec, and says so. |
| `date` omitted | latest publication; `asked_date` is today, so a stale answer is still visible |
| date in the future | **422** `date_in_future`, before any upstream call. "Today" is Frankfurt's today, and the message says so — at 00:30 in Istanbul it is still yesterday at the ECB. |
| date before 1999-01-04 | **422** `date_before_series` (measured: 1999-01-04 answers, 1999-01-03 is a 404) |
| currency code does not exist | **422** `unknown_currency`. The upstream returns the same bare 404 for "no such currency" and "no rate that day", so on a 404 we check its currency list and say which one it was. If that check itself fails we report the 404 we actually have, `no_rate_for_date`, rather than guess. |
| `from` and `to` are the same | **400** `same_currency`. There is no rate to quote, and quoting 1.0 would need a `rate_date` we were never given. |
| upstream slow | **504** `upstream_timeout` (2s connect, 4s read) |
| upstream 5xx, or unreachable | **502** `upstream_unavailable` |
| upstream returns HTML, a document of the wrong shape, no `date`, or a rate that is zero, negative or not a number | **502** `upstream_invalid_response` |
| `amount` missing, `0`, negative, `NaN`, `Infinity`, not a number, or above 1e12 | **422** `invalid_amount`, before any upstream call |
| `amount` with ten decimal places | **accepted.** It is parsed as a `Decimal` and used in full; only `result` is rounded, to two places, half up. Refusing a customer's real amount would be unhelpful and truncating it would be a lie about their money. |
| lowercase `eur` | accepted, echoed back as `EUR` |

## Error codes

| code | status | when |
|---|---|---|
| `invalid_amount` | 422 | the amount cannot mean money |
| `invalid_currency` | 422 | not three letters |
| `unknown_currency` | 422 | well-formed, but the ECB does not publish it |
| `same_currency` | 400 | `from` equals `to` |
| `invalid_date` | 422 | not a `YYYY-MM-DD` date |
| `date_in_future` | 422 | after the last day the ECB could have published |
| `date_before_series` | 422 | before 1999-01-04 |
| `invalid_request` | 422 | a query parameter the framework could not read |
| `no_rate_for_date` | 404 | the upstream has no rate for that day and pair |
| `upstream_timeout` | 504 | the upstream did not answer in time |
| `upstream_unavailable` | 502 | the upstream is unreachable or failing |
| `upstream_invalid_response` | 502 | the upstream answered with something we will not stand behind |
| `not_found` / `method_not_allowed` | 404 / 405 | wrong path or verb |
| `internal_error` | 500 | our bug; logged in full, described in one flat sentence |

## Caching

A repeat of the same question does not re-ask the upstream. The key is
`(from, to, date)` — **the date is in the key**, because a cache that forgets it
answers a question about March with August's rate and looks healthy doing it.

Settled past days are held for 6 hours; `latest` and *today* for 60 seconds,
because nothing is published until the afternoon. Failures are never cached: a
minute of upstream trouble must not become a minute of lying.

## Layout

```
fxtool/validate.py   what we refuse without asking anybody
fxtool/upstream.py   the client; nothing off the wire is trusted
fxtool/cache.py      TTL cache, keyed by pair and date
fxtool/service.py    ties a rate to the day it belongs to, then does the arithmetic
fxtool/errors.py     the error codes and the one envelope
fxtool/main.py       the endpoint
```

`PLAN.md` is how this was built, step by step. `PITFALLS.md` is the list of
mistakes it is written to prevent, each one tied to the test that catches it.
The original brief is the first commit.
