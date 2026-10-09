# Pre-registered: layer 5, do Kalshi's daily index ranges agree with the options market?

Written 2026-10-09, after the live collection started (2026-10-05) and before any live options-vs-Kalshi statistic
was computed. Only data-quality counts have been looked at (collection gaps, fit success). The git commit that adds
this file is the timestamp. This is the comparison the project is named after.

## Question

Every 30 minutes the collector saves SPX and NDX option chains and Kalshi's daily S&P 500 (KXINX) and Nasdaq-100
(KXNASDAQ100) range ladders at the same moment. The options imply a full distribution for the 4pm close
(Breeden-Litzenberger on a fitted SVI smile, `implied/bl.py`); integrating it over each Kalshi range gives the
options market's price for that range. Three questions, per index:

1. **Agreement.** How often does the options probability sit inside Kalshi's bid-ask, and how big are the gaps?
2. **Accuracy.** When they disagree, which one predicts the settlement better?
3. **Tradability.** Does trading Kalshi toward the options price make money after Kalshi's fees, at sizes the
   book actually shows?

## Sample (a forward sample, fixed now)

- **Window:** trading days 2026-10-05 to 2026-11-27 inclusive. The analysis runs once, on or after 2026-11-30.
  Nothing after 2026-11-27 is used.
- These dates are after `FINAL_TEST_START` (2026-04-01). They are live data that did not exist when the holdout
  was set, and this file governs them. The historical April-to-September holdout stays locked for layer 8.
- **Snapshots:** every Kalshi snapshot taken in market hours (13:30 to 20:00 UTC, and at least 5 minutes before
  that day's close), paired with the SPX and NDX option snapshots from the same collection run (time stamps within
  3 minutes). Duplicate runs closer than 10 minutes apart: keep the earlier one.
- **Contracts:** the same-day event only (the ladder that settles at that day's close), matched to the PM-settled
  options expiring at the same close: SPXW for KXINX, NDXP for KXNASDAQ100.
- **Options fit:** `surface_from_snapshot` exactly as in the code at this commit. A fit is used only if its density
  integrates to within 0.05 of 1 with negative mass below 0.01. A contract is used only if every finite edge of its
  range lies inside the fit's quoted strike range (`in_fitted_range`).
- **Quoted:** Kalshi bid > 0, an ask with size, and ask - bid <= 10 cents.
- **Settlement:** Kalshi's own `result` for each market, from `collect/kalshi_history.py` run after the window.

## Decision rules, per index

All intervals: 95%, 2,000 bootstrap resamples of whole trading days (snapshots within a day are not independent).

1. **Agreement (reported, no pass/fail):** share of quoted contract-snapshots with the options probability inside
   Kalshi's bid-ask; mean absolute gap between the options probability and Kalshi's mid, overall and by hours to
   close (6-4, 4-2, 2-0).
2. **Accuracy.** Brier score of Kalshi's mid and of the options probability against settlement, over all quoted
   contract-snapshots. Verdict: "options more accurate" or "Kalshi more accurate" if the interval for the difference
   excludes 0; otherwise "no detectable difference".
3. **Tradability.** For each contract and day, take the first snapshot where the options probability is more than
   3 cents below Kalshi's bid (sell YES at the bid) or more than 3 cents above Kalshi's ask (buy YES at the ask), and
   the quote shows at least 100 contracts at that price. Hold to settlement. Profit per contract includes Kalshi's
   taker fee, 0.07 x P x (1 - P), rounded up to the cent per 100-contract order. Verdict: **edge** if there are at
   least 30 trades on at least 15 days and the interval for mean profit per contract is above 0; **no edge** if the
   interval's upper end is below 0; otherwise **inconclusive**.

## Also reported, not part of any verdict

- Rule 3 split by side (sell vs buy) and for long shots (Kalshi mid of 5 cents or less).
- Rule 3 with thresholds of 2 and 5 cents, and with the mid instead of the touch, to show sensitivity.
- Calibration of the options probability itself (binned predicted vs settled), since it is risk-neutral: it prices
  the fear of a crash, so it should overstate the left tail.

## Known limitations, stated in advance

- About 40 trading days is a small sample for rare outcomes; rule 3 may well end "inconclusive".
- Options probabilities are risk-neutral. A gap is a disagreement, not proof that either side is wrong.
- Collection gaps (the Mac sleeping, GitHub's scheduler) remove some snapshots. Gaps are not related to prices, so
  they cost sample size, not bias. They are reported.

Prediction, written down so it can be wrong: the options probability sits inside Kalshi's spread on most quoted
contracts; where they disagree it is mostly in the tails, with Kalshi priced above the options; Brier shows no
detectable difference; rule 3 is inconclusive on the S&P and has its best chance on the Nasdaq.
Nothing in the method changes after the results are seen. Any failure is reported in the README with its numbers.
