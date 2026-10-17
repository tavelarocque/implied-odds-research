# Pre-registered: layer 5 on Bitcoin, do Kalshi's BTC contracts agree with Deribit's options?

Written 2026-10-09, before collection of the sample started (the first snapshot counted is 2026-10-10). Only the
pipeline has been tested, on two live snapshots taken today and outside the window: that the fit runs, passes its
checks, and gives sensible probabilities. The git commit that adds this file is the timestamp.

## Question

Layer 5 (`research/PREREGISTRATION_LAYER5.md`) on Bitcoin. Kalshi lists a BTC contract set every hour, around the
clock (KXBTCD, "Bitcoin above K at the hour", each set open for its last hour, plus a 5pm ET set open for a day).
Deribit lists BTC options, the deepest crypto options market. Same three questions: how often the options probability
sits inside Kalshi's spread, which predicts settlement better, and whether trading Kalshi toward the options price
makes money after fees. Bitcoin trades seven days a week, so the sample grows faster than the stock version's.

## Sample

- **Window:** Kalshi BTC contracts settling 2026-10-10 to 2026-11-27 (UTC dates). Run once, on or after 2026-11-30.
- **Snapshots:** every run of `.github/workflows/crypto.yml` (hourly at :07, all days; see the note below): Deribit BTC options
  (`collect/deribit_snapshot.py`) and Kalshi KXBTCD (`collect/kalshi_snapshot.py`, saved to `data/raw/kalshi_crypto/`,
  separate from the stock snapshots). Runs closer than 10 minutes apart: keep the earlier. Deribit snapshot within 3
  minutes of the Kalshi one. Contracts with at least 5 minutes to settlement.
- **Options view at Kalshi's settlement time** (`implied/crypto.py`):
  1. Take the first Deribit expiry at or after the Kalshi settlement (Deribit expiries are 08:00 UTC).
  2. Fit raw SVI to Deribit's mark implied volatility at every strike where the out-of-the-money option has a live bid
     or ask (at least 8 strikes), with Deribit's published forward and a zero rate. Mark volatility rather than raw
     quotes because the 0.0001 BTC tick makes quotes on a 12-hour option uninformative beyond about 2% from the money.
  3. Move the smile back to the Kalshi settlement time t, keeping its shape in standard-deviation units:
     w_t(k) = (t / T1) w_1(k / sqrt(t / T1)); forward S (F1 / S)^(t / T1), with S Deribit's BTC index.
  4. Probability of "above K" = minus the derivative of the call price in K (Breeden-Litzenberger), as in layer 5.
  A fit is used only if its density integrates to within 0.05 of 1 with negative mass below 0.01; a contract only if
  its strike lies inside the fitted range after step 3.
- **Quoted, fee, settlement:** exactly as layer 5 (bid > 0, an ask with size, spread at most 10 cents; taker fee
  0.07 x P x (1 - P) rounded up per 100-lot; KXBTCD has no fee multiplier in Kalshi's schedule); Kalshi's own
  `result` per market.

## Decision rules

Layer 5's three rules, unchanged, pooled over all KXBTCD contracts, with 2,000 bootstrap resamples of whole UTC days:
1. **Agreement** (reported): share with the options probability inside Kalshi's bid-ask; mean absolute gap to mid,
   by hours to settlement (under 1, 1 to 6, 6 to 24) and by hourly vs 5pm sets.
2. **Accuracy:** Brier of Kalshi's mid vs the options probability; "options more accurate", "Kalshi more accurate" or
   "no detectable difference" by whether the interval for the difference excludes 0.
3. **Tradability:** first signal per contract (options more than 3 cents past the touch, at least 100 contracts shown),
   held to settlement, after fees. **Edge** if at least 30 trades on at least 15 days and the interval for mean profit
   per contract is above 0; **no edge** if its upper end is below 0; otherwise **inconclusive**.

## Also reported, not part of any verdict

Rule 3 by side, long shots (mid 5 cents or less), hourly vs 5pm sets, and thresholds of 2 and 5 cents and the mid.
Calibration of the options probability, which is also the check on step 3: if moving the smile in time is badly wrong,
the options probability will be miscalibrated in a visible direction.

## Known limitations, stated in advance

- **Time scaling.** Variance is assumed to accrue evenly in calendar time. Bitcoin is quieter at night and at weekends,
  and Deribit's next expiry is often 10 to 23 hours after a Kalshi hourly settlement, so the options view of a
  one-hour contract is mostly extrapolated. This is the weakest link and the main reason the BTC verdict should be read
  more cautiously than the stock one.
- **Different settlement prices.** Kalshi settles on CF Benchmarks' real-time index (an average over the final minute);
  Deribit's expiry uses its own index (a 30-minute average). The options are only used for their smile here, and spot
  comes from Deribit's index, so this costs a little precision near the money, not a bias.
- **Mark volatility** is Deribit's model of its book, not a trade price.
- Risk-neutral probabilities, collection gaps and sample size: as layer 5. GitHub's scheduler is unreliable and there
  is no laptop backstop for nights and weekends, so expect gaps.

Prediction, written down so it can be wrong: agreement near the money is close (the options probability inside or
within a cent or two of Kalshi's spread), Kalshi's long shots are priced above the options (as on the S&P), Brier shows
no detectable difference, and rule 3 is inconclusive or "no edge" once fees are paid, with long-shot sells the only
part that looks positive.
Nothing in the method changes after the results are seen. Any failure is reported in the README with its numbers.

## Note, 2026-10-09, before the window opened

The collection schedule was cut from every 30 minutes to hourly at :07, for cost: every 30 minutes would have used most
of the account's free GitHub Actions minutes and risked stopping the stock collection with it. Each hourly KXBTCD set
is open for one hour, so each is still captured once, about 53 minutes before it settles; the 5pm ET set is captured
about 24 times. Nothing else changes. Written before the first snapshot counted (2026-10-10 00:00 UTC).

## Known limitation, noted 2026-10-16 (no change to the method)

Some fitted smiles have a near-sharp kink (SVI s of order 1e-6). For a strike within a few dollars of the kink,
p_opt depends on the finite-difference step: 2 of 13,804 contract-snapshots (2026-10-15 to 17) move by more than
1 point when the step shrinks 100-fold. The method stays as registered; layer 15 (amendment 2026-10-16) reports
whether any conclusion depends on these contracts. A future layer that fits smiles should put a floor on s.
