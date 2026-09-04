# Review of tool.py

I ran the working code against the real ECB service. I found a few serious
problems.

## 1. The cache ignores the date

The cache key is built from the currency pair only:

`EUR-TRY`

So the rate fetched for one date keeps being used even when a different date is
asked for later.

For example, after the rate for 29 August has been fetched, asking for 12 March
2020 returns that same rate. The ECB gives a different rate for that date.

This is one of the most serious problems, because a completely wrong result can
be returned to the customer with a 200 status.

**Fix:** add the date to the cache key, and give the cache a TTL.

**How I checked:** started the service and asked for two different dates in a
row, then compared the second answer with the upstream's own answer for that
date. The ECB gives 7.0361 for 12 March 2020; tool.py returns 56.17. On 250 EUR
that is 14,042.50 TRY instead of 1,759.03.

## 2. The API parameters do not match the brief

The endpoint expects `from_` and `on`. The given contract uses `from` and `date`.

Because FastAPI does not reject unknown parameters, a caller who follows the
correct contract does not get an error. They get a different result, produced
from the default values.

For example, even when the caller sends `from=USD`, the service does not see it
and can use `EUR` instead.

Returning a 422 here would have been safer than quietly giving a wrong result.

**How I checked:** called the URL from the brief exactly as written.
`?amount=250&from=EUR&to=TRY&date=2026-08-28` came back with
`"rate_date": "2026-09-04"`, so the date I sent was dropped.

## 3. `rate_date` is wrong

The upstream response contains the real date of the rate, but instead of using it
the code writes the date the caller asked for as `rate_date`.

For example, if the ECB returns Friday's rate for a Saturday, the response shows
Saturday instead of Friday.

That can then make the model give the customer wrong information.

**Fix:** `rate_date` should be taken directly from the upstream's `date` field.
The date the caller asked for should be kept separately, as `asked_date`.

**How I checked:** asked both the upstream and tool.py about Saturday 29 August.
The upstream says `"date": "2026-08-28"`; tool.py says
`"rate_date": "2026-08-29"`.

## Other problems

* On failure the code returns `200` and `0.0`. That makes a real error look like
  a successful response.
* The rate is rounded to two places before the calculation. This causes an
  unnecessary loss of precision.
* There is no check on `amount` for negative values or `NaN`.
* The upstream URL is hardcoded, so the tests end up depending on the real
  service.

## The one I would fix before shipping tonight

If I had to pick a single change, I would add the date to the cache key. As it
stands, a plainly wrong rate can be used for a different date.

But I would not consider that enough for a release on its own. Until the
`rate_date` problem and the errors coming back as `200` are also fixed, the
service cannot be called reliable.

## Things that look suspicious but are fine

Some things look like problems at first but are not:

* No timeout is set for `httpx`, but there is a default timeout.
* The module-level dictionary does not cause data corruption in an async setting.
  Two cache misses arriving at the same time can send two requests to the
  upstream, but nothing is corrupted.
* Using the previous business day's rate for a weekend is sensible. The problem
  is that the response does not state it with the correct date.
