# Pre-registered: does activity on Kalshi's index ladders excite itself? (Hawkes model)

Written 2026-10-04, after the model was built and tested on simulated data (`tests/test_hawkes.py`) and before it
was fitted to any real data. The git commit that adds this file is the timestamp. Measurement only: any trading or
quoting rule built on the answer gets its own pre-registration later.

## Question

When a Kalshi S&P 500 or Nasdaq-100 range ladder becomes active (quotes move, trades print), does that activity make
more activity likely in the next few minutes, beyond the normal ramp into the close? If so, how strong is the effect
(the branching ratio n: extra events each event triggers) and how fast does it fade (half-life)? This tells us whether
these markets have "bursts" a market maker or a liquidity-taker would need to plan around, and it is the
microstructure fact a quoting model in a later layer would build on.

## Data

- Series: KXINX (S&P 500) and KXNASDAQ100 (Nasdaq-100), range ladders that settled yes or no.
- Days: every pre-holdout day with 1-minute candles, 2025-10-16 to 2026-03-31. The holdout from 2026-04-01 is not used.
- Window: the 360 minutes before each day's close time (normally 10:00 to 16:00 ET; on early-close days, the 360
  minutes before that close). Minute j holds candles whose end_period_ts falls in (close - 360 + j, close - 360 + j + 1]
  minutes.
- Kalshi writes a 1-minute candle for a contract only when something in it changed. Two event counts per minute:
  - **Activity (primary):** how many of the day's contracts have a candle in that minute.
  - **Trades:** how many of the day's contracts have a candle with volume > 0 in that minute.

## Model (`microstructure/hawkes.py`)

lambda_t = b_t + n * E_t, with E_t = phi * E_{t-1} + (1 - phi) * N_{t-1}, Poisson counts, days independent, E = 0 at
the start of each day. log b_t is piecewise linear with knots every 15 minutes, fitted jointly with n and phi by
maximum likelihood. The half-life is capped at 30 minutes. Both choices were fixed on simulated data before seeing
real data: a constant baseline turns a pure ramp into n = 0.89; a baseline from raw averages biases n low; without the
cap a slow kernel can stand in for the ramp.

## Decision rules, per index and per count (four verdicts)

95% intervals from 1,000 bootstrap resamples of whole trading days (the same resampled dates for both indexes, so
the S&P-minus-Nasdaq difference has a paired interval).

1. **Self-excitation:** confirmed if the lower end of the interval for n is above 0.10. Upper end below 0.10: "no
   meaningful self-excitation". Otherwise: "inconclusive". (0.10, not 0, because on simulated data with no
   self-excitation the fit returned n up to 0.04.)
2. **Speed:** reported only if rule 1 confirms: the half-life with its interval. If the estimate sits at the 30-minute
   cap, the verdict is "slow, not separable from the baseline", not a confirmed fast effect.
3. **S&P vs Nasdaq:** n differs if the paired interval for the difference excludes 0.

## Also reported, not part of any verdict

- The same fit with a constant baseline, to show the size of the intraday-ramp confound on real data.
- Likelihood-ratio statistic against the same baseline with n = 0.
- Pearson dispersion of the residuals (the Poisson assumption; the day bootstrap does not rely on it).
- Robustness: dropping the last 10 minutes; October to December vs January to March.

## Known limitation, stated in advance

Both indexes move with volatility that clusters on its own. A burst of index movement re-prices every contract in a
ladder, so part of any measured n can be a common driver (the index itself) rather than Kalshi traders reacting to
each other. This study cannot separate the two; it measures whether bursts exist and how long they last, not why.

Prediction, written down so it can be wrong: activity is self-exciting on both indexes (n well above 0.10) with a
half-life under 10 minutes, and trades are less self-exciting than quote activity.
Nothing in the method changes after the results are seen. Any failure is reported in the README with its numbers.

## Addendum, 2026-10-04 (after the real-data point estimates were seen, before the bootstrap finished)

The point estimates of n came out at 0.88 to 0.98. Testing why, I found a confound the pre-registered model does not
handle: **day-level heterogeneity**. The model shares one baseline across all days. If some days are busy all day and
others quiet, the shared baseline under-predicts a busy day from start to finish, and the excitation term (recent
activity) fills the gap. On simulated days whose levels vary by about 50% and which have no self-excitation at all,
the pre-registered fit returns n = 0.999. Adding a multiplicative level per day returns n = 0.000 on the same data and
about 0.45 when the true n is 0.5 (slightly biased low). Both are now checks in `tests/test_hawkes.py`.

What changes and what doesn't:
- The pre-registered analysis runs exactly as written and its four verdicts are reported as the official result.
- The day-effects refit (`research/posthoc_hawkes_day_effects.py`) is reported beside it, labelled post hoc,
  with the same 0.10 bar and day bootstrap. It was chosen after the point estimates were seen, so it is evidence of
  lower standing than the pre-registered result, even though it is the better-specified model.
- Any later study that relies on n uses the day-effects model and is pre-registered with it.
