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
