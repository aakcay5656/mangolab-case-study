# Notes

## Decisions

When the ECB published no rate for the day asked, I use the last valid rate the
upstream returns. I do not present that rate as if it belonged to the day asked.
`rate_date` comes from the upstream, `asked_date` comes from the date the caller
asked for. So if we are using Friday's rate for a Saturday, we can tell the
customer that.

I did not set a maximum number of days for the backfill. Showing the date gap
openly seemed more correct to me than hiding it. But if the upstream returns a
rate newer than the date asked for, I refuse the request.

My other decisions:

* If `date` is not given, today is assumed.
* Today is worked out on the ECB's Frankfurt calendar.
* For `from == to` I return 400. I did not want to produce a result by assuming
  a date that does not exist.
* The amount is handled as a `Decimal`, and only the final result is rounded to
  two places. I do not round the rate itself.
* Validation runs before the network request.

## With another day

First I would test it with a real model. In particular I would check whether the
model passes the difference between `rate_date` and `asked_date` on to the
customer correctly.

I would also add a lock per cache key, so that requests arriving at the same time
do not go to the upstream over and over. For the second request made on the 404
path I would add a timeout that covers the whole operation.

Finally I would prepare a tool definition that agents can use directly. In the
description I would state the supported currencies, what the dates mean, and that
the tool does not forecast future rates.

## AI tools

I used only Claude Code for this case. I started with a plan and a pitfalls list,
then worked in small steps and wrote tests for each step.

I checked with 13 mutations that the tests really do catch the guards. I also
verified the upstream's behaviour with `curl` instead of guessing it. That is how
I saw that `/v1/latest` has to be used rather than `/latest`, and that the series
starts on 1999-01-04.

## One thing the AI got wrong

In the cache tests, the fake upstream Claude Code produced did not imitate the
real service correctly. It returned `"date": "latest"` and ignored the symbol.
Three tests failed because of that.

When I looked, I saw the problem was in the test double, not in the production
code. The response validation was already rejecting the invalid date. I fixed the
fake and left the production code alone.

It showed me that when a test fails, you have to question the test as well as the
code.
