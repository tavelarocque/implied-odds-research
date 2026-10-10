# Pre-registered: layer 13, de-compressing Kalshi's 5pm Bitcoin prices with a plain lognormal model

Written 2026-10-10, after layer 12's development result (README) and before anything below has been computed on the
holdout or on the forward window. The git commit that adds this file, and `research/test_layer13_lognormal.py` with it,
is the timestamp.

## Where it comes from

Layer 12 (development sample, 5pm KXBTCD sets settling 2025-09-01 to 2026-03-31) found, as a check made after its
pre-registered tests, that a plain lognormal model of the spot price carries information Kalshi's price leaves out:
alongside Kalshi's mid its log-odds coefficient was +0.50 (1 hour out) and +0.45 (3 hours out), both with intervals
clear of 0, and on its own its Brier score was level with Kalshi's (0.070 vs 0.070 at 1 hour; 0.075 vs 0.076 at 3).
Kalshi's 5pm prices are also too close to 50% (logistic calibration slope about 1.3, layer 11's development work). This
layer asks whether a fixed blend of the two beats Kalshi's price on data it was not fitted to.

## The forecast, frozen

- **Kalshi:** the mid of the last hourly candle ending at or before the quote time and within an hour of it; yes bid
  > 0, ask < 1, ask > bid, spread at most 10 cents. Quote times 1 and 3 hours before the 5pm ET settlement.
- **Lognormal:** S = the Coinbase BTC-USD close of the last completed hour at the quote time; sigma = the standard
  deviation of the 23 hourly log returns within the 24 hourly candles ending then, times sqrt(h); zero drift;
  P(above K) = N(ln(S/K) / sigma).
- **The blend:** logit P = b x logit(Kalshi mid) + c x logit(lognormal), probabilities clipped to 0.5%-99.5% inside
  the logits, **no intercept** (no view on direction: a directional intercept is the part least likely to carry over
  from one six-month window to the next). Fitted by maximum likelihood on the development window above and frozen:
  - 1 hour out: b = 0.794, c = 0.414
  - 3 hours out: b = 0.846, c = 0.432
- **Contracts:** Kalshi's 5pm ET Bitcoin sets (KXBTCD, events ending in 17, "greater" strikes, open at least 2 hours
  before settling, settled yes or no), every strike within 6% either side of S. A settlement day and horizon with no
  Coinbase candle for the quote hour is left out (as layer 12, amendment 2).

## Primary test (the verdict), per horizon

Mean over contracts of Brier(blend) - Brier(Kalshi mid), 97.5% interval from 2,000 resamples of whole settlement days
(Bonferroni over the two horizons).

- **The blend beats Kalshi** at a horizon if the whole interval is below 0; **Kalshi beats the blend** if above 0;
  otherwise **no difference shown**.
- Layer 13 **passes a test** if the blend beats Kalshi at either horizon.

## Secondary and description (reported, not part of the verdict)

- The lognormal alone vs Kalshi: Brier difference, 95% day-bootstrap interval.
- CORP decomposition (miscalibration, discrimination, uncertainty) of the blend, Kalshi and the lognormal.
- **Trading, description only:** buy YES at the ask when blend - ask - fee > 3 cents, buy NO at 1 - bid when
  bid - blend - fee > 3 cents, hold to settlement, Kalshi's taker fee 0.07 x P x (1 - P) rounded up per 100
  contracts. Mean profit per contract with a day-bootstrap interval. If the blend wins, a trading rule gets its own
  pre-registration; this number only sizes whether one is worth writing.

## Test A: the holdout, run once

Sets settling 2026-04-01 to 2026-09-30: `UNLOCK_HOLDOUT=1 python3 research/test_layer13_lognormal.py A`, once; the
result goes in the README whatever it is.

What of this window has been seen: layers 11 and 11b (2026-10-09) looked only at downside long shots with a mid of 90
cents or more, and reported profit and loss rates for them, not calibration or Brier across strikes. Nothing about the
lognormal model or the blend on this window has been computed. Candles for strikes up to 6% above the decision-time
price were added before this test (`LAYER11_HOLDOUT=1 FILL_ABOVE=1 python3 collect/kalshi_btc_fill.py`, started
2026-10-10 before this file was committed; downloading only).

## Test B: forward

Sets settling 2026-10-15 to 2027-01-31, analysed once on or after 2027-02-01, from Kalshi's historical candles and
Coinbase's hourly candles downloaded after the window closes, with the same code and the same frozen coefficients.

## Prediction, written so it can be wrong

The blend beats Kalshi at 3 hours in test A by a small margin (under 0.003 Brier), with no difference shown at 1 hour.
The trading description is near zero or negative after fees, because the blend mostly moves prices away from 50% on
contracts whose spreads already cover the gap.

Nothing above changes after the results are seen.
