# Pre-registered: layer 3, who leads price discovery, Kalshi or Polymarket?

Written 2026-10-04, after the 1-minute Kalshi download started and before any minute-level result was computed.
The git commit that adds this file is the timestamp. Measurement only: any trading rule built on the answer gets its
own pre-registration later.

## Question

Kalshi's S&P 500 and Nasdaq-100 range ladders and Polymarket's daily "up or down" markets price the same event:
will the index close above the previous close? Layer 6 showed the two venues disagree by several points and the gap
shrinks toward the close. When they disagree, which one moves to meet the other? The venue that does most of the
moving is the follower; the other is where new information shows up first.

## Data

- Days: 2025-10-16 (first day Polymarket's market compares with the previous close) to 2026-03-31. The holdout
  from 2026-04-01 is not used.
- Pairs: KXINX vs Polymarket `spx-up-or-down`, and KXNASDAQ100 vs Polymarket `ndx-up-or-down`, the same day
  matching and rule filters as `research/cross_venue.py`; K = Kalshi's previous-day settlement value.
- Grid: every 10 minutes from 6 hours to 20 minutes before the 4pm ET close.
- Polymarket: the Up price at the last 10-minute observation at or before each grid time (missing if older than
  10 minutes).
- Kalshi: for each range contract, the yes bid of its last 1-minute candle at or before the grid time. Kalshi only
  writes a candle when something changes, so a quiet contract keeps its last quote; before a contract's first
  candle in the window, its quote is that candle's opening value. P_K = P(close > K) from the bids-only ladder
  (`implied.kalshi_ladder.prob_above`, method "bid"), the estimator layer 6 settled on.

## Estimand

gap(t) = P_poly(t) - P_K(t). Changes over the next 10 minutes: dK(t) = P_K(t+10) - P_K(t), dP(t) likewise.

Each quote has noise (bid-ask bounce, stale prints), and noise in today's gap mechanically reverses in the next
interval, which would make the noisier venue look like the follower. To keep that out, the gap is measured one
interval *before* the change it predicts:

    dK(t) = aK + bK * gap(t - 10) + error
    dP(t) = aP + bP * gap(t - 10) + error

Pooled over grid times and days, per index. If Kalshi follows, bK > 0; if Polymarket follows, bP < 0.
Kalshi's share of the adjustment: s = bK / (bK - bP).

## Decision rules, per index (S&P 500 and Nasdaq-100 separately)

95% intervals from 2,000 bootstrap resamples of whole trading days.

1. **Does the gap close at all?** bK - bP > 0 with an interval that excludes 0. If not: "the gap does not close at a
   10-minute horizon", and rule 2 is not evaluated.
2. **Who leads?** s above 0.5 with an interval excluding 0.5: Polymarket leads (Kalshi does most of the moving).
   s below 0.5 with an interval excluding 0.5: Kalshi leads. Otherwise: no detectable leader.
3. **Permutation check (Masters).** Pair each day's lagged gaps with another day's price changes, 1,000 times, and
   recompute bK - bP. A verdict from rule 1 stands only if the real value beats the shuffled ones with p < 0.01.

## Also reported, not part of any verdict

- Cross-correlation of the two venues' 10-minute changes at lags of -30 to +30 minutes.
- The same regressions with the bid-ask midpoint Kalshi estimator, and with the unlagged gap, to show how much the
  noise correction matters.
- Results split by hours before the close (6-4, 4-2, 2-0).

Prediction, written down so it can be wrong: Polymarket's Nasdaq market is thin (median volume about $7,300 a day
against $143,000 for the S&P), so on the Nasdaq Kalshi should lead; on the S&P either venue could.
Nothing in the method changes after the results are seen. Any failure is reported in the README with its numbers.
