# Pre-registered: layer 7, how fast does Kalshi react when the index moves?

Written 2026-10-09, before any minute-level Kalshi-vs-index statistic on the live sample was computed. The git
commit that adds this file is the timestamp. Measurement only: any trading rule built on a lag gets its own
pre-registration.

## Question

When the S&P 500 or the Nasdaq-100 moves, how many minutes does it take Kalshi's same-day range ladder to price
the move in? A ladder that reacts within the same minute leaves nothing for a faster trader. One that takes several
minutes is stale, and quoting against a stale ladder is the cleanest edge a retail-sized trader could have.

## Sample (the same forward window as layer 5)

- **Days:** trading days 2026-10-05 to 2026-11-27. The analysis runs once, on or after 2026-11-30. These are live
  dates after `FINAL_TEST_START`, governed by this file; the historical holdout stays locked for layer 8.
- **Index:** one-minute closes of ^GSPC and ^NDX from `collect/intraday.py` (Yahoo Finance; ^NDX added
  2026-10-09, and its seven-day lookback covers the whole window). Files overlap; de-duplicate on timestamp.
- **Kalshi:** one-minute candles of every market in the same-day KXINX and KXNASDAQ100 range ladders, downloaded
  after the window with `collect/kalshi_history.py`. For each minute, each contract's yes bid is the close of its
  last candle at or before that minute (Kalshi writes a candle only when something changes).
- **Grid:** every minute from 360 to 10 minutes before the day's close. A Yahoo bar stamped t covers t to t+1, so
  it is matched to the Kalshi minute ending at t+1.

## Estimand

Kalshi's implied median close M_t: the level where the bids-only ladder (`implied.kalshi_ladder`, method "bid",
the estimator layers 3 and 6 use) puts 50% above and 50% below, interpolated with the same monotone cubic as
`prob_above`. Minute changes dM_t and index changes dS_t, both in index points. Pooled per index, within days:

    dM_t = a + sum_{j=-5..10} b_j * dS_{t-j} + error

j > 0: the index moved j minutes earlier. j < 0: the index moves later (Kalshi leading).

- **Total response** B = sum of b_0..b_10. 1 means Kalshi fully prices the move within ten minutes.
- **Same-minute share** b_0 / B.
- **50% and 90% times:** the smallest lag L at which b_0 + ... + b_L reaches 50% (90%) of B.
- **Lead sum** b_-5 + ... + b_-1.

## Decision rules, per index

95% intervals from 2,000 bootstrap resamples of whole days.

1. **Speed.** "Fast" if the interval for the 90% time ends at 2 minutes or less; "slow" if it starts at 5 minutes or
   more; otherwise "moderate", with the interval reported.
2. **Completeness.** "Underreacts" if the interval for B lies below 1; "overreacts" if above 1; otherwise "complete".
3. **Lead.** "Kalshi leads the index" if the interval for the lead sum excludes 0. Expected not to: a lead would
   point to a timestamp problem in the data before it pointed to informed traders.

## Also reported, not part of any verdict

- The same by hours to close (6-4, 4-2, 2-0).
- S&P minus Nasdaq 90% time, paired by day.
- Coverage: minutes with both prices, days lost to missing data.

## Known limitations, stated in advance

- One-minute resolution: anything faster than a minute shows as lag 0.
- Yahoo's index minutes are not exchange-grade; small timestamp offsets would show up as a lead or extra lag.
- The median ignores everything else about the distribution. A move that changes the width but not the centre
  is invisible here.

Prediction, written down so it can be wrong: most of the response arrives in the same minute and the next one
(S&P "fast"), the Nasdaq ladder is slower than the S&P's, B is slightly below 1, and there is no lead.
Nothing in the method changes after the results are seen. Any failure is reported in the README with its numbers.
