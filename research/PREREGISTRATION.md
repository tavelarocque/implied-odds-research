# Pre-registered: Nasdaq-100 replication

Written 2026-10-03, before any Nasdaq-100 result was computed. The git commit that adds this file is the
timestamp. The analyses are the same code as the S&P 500 studies, run with the series switched.

## What is being replicated

1. **Calibration (layer 4)** on Kalshi's Nasdaq-100 daily range contracts (KXNASDAQ100), April 2022 to
   March 2026, the same holdout excluded.
2. **Cross-venue comparison (layer 6)** of Kalshi's Nasdaq-100 ladder against Polymarket's daily
   "NDX up or down" markets, over whatever days overlap before the holdout.

## Criteria, fixed in advance

Calibration replicates if all three hold:
- The favourite-longshot slope b is above 1 at 1 hour or 3 hours before the close, with a 95% day-level
  bootstrap interval that excludes 1 (S&P: 1.09 and 1.11).
- No price bucket is profitable for a taker after spread and fees.
- The 1-hour slope in 2025-26 is closer to 1 than in 2022 (the bias faded).

Cross-venue replicates if all three hold:
- Using the bids-only Kalshi estimate, the mean absolute gap is smaller one hour before the close than
  six hours before.
- The Brier-score difference between venues is not significant at any horizon.
- No package guaranteed to pay $1 costs less than $1 after fees.

Any criterion that fails is reported as a failure, with the numbers, in the README. Nothing in the method
(horizons, filters, estimators, fees) changes after the Nasdaq results are seen.


## Addendum: one holdout test (written 2026-10-03, before the holdout was opened)

The Nasdaq-100 calibration found one price bucket that made money for a taker, against the pre-registered
criteria. It may be chance: the study checks about 100 bucket, side and horizon combinations. It gets exactly one
test on the locked holdout (2026-04-01 onward), which no analysis has used. The rule and the bar are fixed here,
the script (`research/holdout_longshot.py`) is committed with this text, and neither changes after the run.

**Rule.** One hour before the 4pm ET close, take every KXNASDAQ100 range contract whose hourly quote is no more than
an hour old, has a bid above 0, an ask below $1 and a spread of 10 cents or less, and whose bid-ask midpoint is
2 cents or less. Sell YES at the bid (buy NO). Profit per contract = bid - outcome - 0.07 x bid x (1 - bid).
Same filters, prices and fee formula as `research/calibration.py`.

**Pass.** The mean profit per contract is above zero with a 95% interval, resampling whole trading days
(2,000 resamples), that excludes zero. Anything else is a fail, and the result is reported in the README
either way.

**Also reported, not part of pass or fail:** the same profit with Kalshi's fee rounded up to a cent per order of
100 contracts; the number of contracts that settled YES (each loses about 99 cents); and the profit per trading day
from selling one contract of every qualifying range.
