# Pre-registered: layer 7b, how fast do Kalshi's hourly contracts react when the index moves?

Written 2026-10-09, before any minute-level hourly-contract statistic on the live sample was computed. Only data
quality has been looked at: market counts, strike spacing, candle density, and the share of minutes where the median
below is defined on one day (2026-10-08). The git commit that adds this file is the timestamp. Measurement only: any
trading rule built on a lag gets its own pre-registration.

## Question

Layer 7 asks how fast the daily range ladder prices an index move. Kalshi also lists hourly contracts: every trading
hour from 10am to 4pm ET, a set of "S&P 500 (or Nasdaq-100) at or above K at the hour" markets (series KXINXU and
KXNASDAQ100U). In their last hour they are close to a pure bet on the next few minutes of the index, so they are where
a slow quote would cost its market makers most, and where a fast trader would look first. Same question, same method,
for these contracts.

## Sample

- **Days:** trading days 2026-10-05 to 2026-11-27, the window of layers 5 and 7. Run once, on or after 2026-11-30.
  Live dates after `FINAL_TEST_START`; the historical holdout stays locked for layer 8.
- **Index:** one-minute closes of ^GSPC and ^NDX, exactly as in layer 7.
- **Events:** every hourly event in KXINXU and KXNASDAQ100U that closes on the hour on those days (the 4pm event
  included). For each event, the minutes from 60 to 5 minutes before its close.
- **Strikes:** the event's "at or above" markets with a strike within 1% of the value the event settled on. This choice
  only limits the download (each Nasdaq event lists 400 strikes); a 1% move inside the last hour is rare, and any minute
  where the 50% level falls outside the downloaded strikes is dropped, not filled.
- **Kalshi prices:** one-minute candles downloaded after the window
  (`collect/kalshi_history.py candles --series KXINXU KXNASDAQ100U --period 1 --since 2026-10-05 --hours-before 1.2
  --near 1`). Each contract's yes bid at a minute is the close of its last candle at or before that minute. An event is
  used only if candles exist for at least 80% of its strikes.

## Estimand

The implied median M_t of each event: the level where the probability of finishing at or above it, read from the
contracts' yes bids, crosses 50%. Bids are made non-increasing in the strike (running minimum from the lowest strike)
and interpolated linearly between the two strikes around 50%. Using bids rather than mids shifts the level by a roughly
constant amount, which drops out of minute-to-minute changes.

The regression, lag definitions, total response B, same-minute share, 50% and 90% times and lead sum are those of
layer 7 (`research/PREREGISTRATION_LAYER7.md`), fitted per index on all events pooled. Differences and lags are taken
within one event's block only, on a strict one-minute clock: a missing minute leaves a gap, and nothing is differenced
across two events.

## Decision rules, per index

The three rules of layer 7, unchanged: speed (fast / moderate / slow from the 90% time interval), completeness (B
against 1) and lead (lead-sum interval against 0). 95% intervals from 2,000 bootstrap resamples of whole days.

## Also reported, not part of any verdict

- The same split by the event's close time (10am to 4pm ET).
- S&P minus Nasdaq 90% time, paired by day.
- Coverage: events used, minutes with a defined median, days lost.
- Next to layer 7's daily verdicts, without a formal test: whether the hourly contracts are faster or slower.

## Known limitations, stated in advance

Those of layer 7, plus: the first event (10am ET) has only its last 30 minutes inside market hours; strikes are 5 points
apart on the S&P and wider on the Nasdaq, so a single strike's bid jumping can move the median by a strike's width in one
minute. That noise sits in dM and widens the intervals; it does not bias the lag pattern.

Prediction, written down so it can be wrong: the hourly contracts are faster than the daily ladder (both indices
"fast"), B is close to 1, and there is no lead. If any market in this project is slow, it will be the Nasdaq hourly.
Nothing in the method changes after the results are seen. Any failure is reported in the README with its numbers.
