# Pre-registered: layer 11b, selling Kalshi's downside Bitcoin long shots when a hidden Markov model says turbulent

Written 2026-10-09, after the exploratory run on the development sample (`research/explore_regimes.py`, README) and
before the layer 11 holdout (Kalshi Bitcoin data settling 2026-04-01 to 2026-09-30) has been analysed by anything.
The holdout's candles were still downloading when this was committed; no result from them has been computed or seen.
The git commit that adds this file, and `research/test_layer11b.py` with it, is the timestamp.

## The rule

- **Contracts:** as layer 11 (`research/PREREGISTRATION_LAYER11.md`): Kalshi's 5pm ET Bitcoin sets (KXBTCD, events
  ending in 17, open at least 2 hours before they settle), every "BTC above K" contract.
- **Turbulent day:** a settlement day D on which the regime model's probability of the turbulent state is above 0.5.
  The model, exactly as `fit`, `walk_forward` and the helpers in `research/explore_regimes.py` at this commit:
  - Yahoo Finance BTC-USD daily bars (UTC days). Observations: the day's log close-to-close return and the log of its
    log high/low range (range floored at 0.00001), each standardized with the training years' mean and SD.
  - A two-state Gaussian hidden Markov model (diagonal covariance), fitted by EM from a range-rank start and a jittered
    one (plus the previous year's fit), states ordered by mean range so the higher-range state is "turbulent".
  - Walk-forward: for settlement year Y the model is fitted on all bars before year Y (refits from 2017; for the
    holdout, on bars up to 2025-12-31). Only filtered probabilities: the forward probability at the close of the UTC
    day before D, from bars up to that day, multiplied by the transition matrix.
- **Trade:** as layer 11. 3 hours before settlement, every contract with yes bid and ask both quoted, spread at most 10
  cents and mid of 90 cents or more. Buy 1 YES at the ask, hold to settlement, Kalshi's taker fee 0.07 x P x (1 - P)
  rounded up per 100-contract order. Every turbulent day, whether or not layer 11's fear-or-funding signal is on.
- **Also reported, not part of the verdict:** 1 hour before; non-turbulent days; turbulent days split by layer 11's
  signal (the part this rule adds is turbulent days without a fear-or-funding signal).

## The verdict (the same bar as layer 11)

- Break-even loss rate p* = mean over trades of (1 - ask - fee).
- **Edge** if at least 40 trades on at least 20 turbulent days, and the exact one-sided 95% (Clopper-Pearson) upper
  bound on the loss rate is below p*, per trade and per day (a day with any loss counts as a losing day).
- **No edge** if the one-sided 95% lower bound on the per-trade loss rate is above p*.
- **Inconclusive** otherwise. Mean profit per contract with a day bootstrap reported as description.

## Test A: the holdout, run once, together with layer 11's

Sets settling 2026-04-01 to 2026-09-30, the same data and the same day as layer 11's test A:
`UNLOCK_HOLDOUT=1 python3 research/test_layer11b.py`, once. The result goes in the README whatever it is.

## Test B: live, forward

Sets settling 2026-10-10 to 2027-01-31, from the live crypto snapshots: the snapshot nearest 3 hours before settlement
and within 30 minutes of it, as layer 11. The model fitted on bars up to 2025-12-31 for 2026, and on bars up to
2026-12-31 for 2027. Analysed once, on or after 2027-02-01.

## What the development sample showed, and the limitations

- 2024-03 to 2026-03, 3 hours out: on turbulent days downside long shots were overpriced by 4.1 cents vs 1.6 on other
  days (difference +2.5, +0.8 to +4.7). On turbulent days without a fear-or-funding signal, selling them made +2.0 cents
  vs -1.6, and 0.8% paid out vs 4.3%. One hour out: no clear difference.
- This was picked from several comparisons (two and three states, two horizons, signal and non-signal days) on the same
  development sample that produced layer 11. It overlaps layer 11 on about half its days. A two-state model on daily
  bars mostly tracks volatility; the S&P version added nothing beyond the VIX and the 50-day trend.
- The prediction, written so it can be wrong: verdict "inconclusive" or "edge", mean profit positive.
Nothing in the rule changes after the results are seen.
