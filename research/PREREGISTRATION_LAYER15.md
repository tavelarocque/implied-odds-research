# Pre-registered: layer 15, two measures: is the gap Kalshi's mistake or the options' premium?

DRAFT 2026-10-13. Not registered until the commit that adds this file, which must land before 2026-11-27 (the last
day of layer 5's window) and before anyone computes a live options-vs-Kalshi statistic. Layers 5 and 5-BTC are
unchanged; this file adds analyses that run on the same sealed data at the same time, once, on or after 2026-11-30.

## Why

Layer 5 compares Kalshi with option-implied probabilities. Those are risk-neutral (Q): they carry the variance risk
premium and crash-insurance demand, so they are expected to be too wide. The 2026-10-13 literature sweep
(`research/reading-list-2026-10-13.md`: Portnaya 2026; Diercks, Katz & Wright 2026; Bartlett & O'Hara 2026)
says a Kalshi-vs-options gap is partly a wedge between venues, not a Kalshi error. Layer 5 alone cannot tell
"Kalshi is wrong" from "options carry a premium". This layer scores each source against what actually happened.

## Sample

Exactly layer 5's and layer 5-BTC's samples (`PREREGISTRATION_LAYER5.md`, `PREREGISTRATION_BTC.md`): same windows,
snapshots, contracts, fit filters, quote filter and settlement source. Every quoted contract-snapshot, traded or not.

## Analyses, per index (S&P 500, Nasdaq-100) and for Bitcoin

Intervals: 95%, 2,000 bootstrap resamples of whole settlement events (one trading day for the index ladders, one
settlement hour for Bitcoin), because every contract on one ladder shares one outcome.

1. **Options calibration (primary).** Fit logit P(y=1) = a + b * logit(p_opt) by maximum likelihood. b > 1 means
   the options distribution is too wide (probabilities too moderate); b < 1 too narrow. Verdict: "options too wide"
   if the interval for b is entirely above 1, "too narrow" if entirely below, otherwise "no detectable miscalibration".
2. **Kalshi calibration (primary).** The same with Kalshi's mid.
3. **Reading rule, fixed now.** Options too wide and Kalshi not miscalibrated: layer 5's gaps are mostly the options'
   premium, and any layer 5 profit is a volatility-premium trade, not a correction of Kalshi. Both miscalibrated in the
   same direction: neither is a clean benchmark. Kalshi miscalibrated and options not: layer 5's premise holds.
4. **Gap persistence (reported).** For Bitcoin hourly contracts, the AR(1) half-life of (Kalshi mid - p_opt) across
   consecutive snapshots of the same contract.
5. **Executable check (reported).** Rule 2 repeated with Kalshi's bid and with its ask in place of the mid, which
   bounds how much of any Kalshi miscalibration a trader could actually capture.
6. **YES-side optimism (reported).** Following Bartlett & O'Hara (2026): Kalshi's mid minus the settled YES rate,
   by probability bin, for contracts whose YES pays on a rise vs on a fall (Bitcoin "above" contracts far below spot are
   downside long shots on the NO side). Tests whether the downside long-shot overpricing is a YES-demand effect.

## Output frozen for the forward test (layer 16)

On the same run, fit a one-parameter variance rescale of the options distribution (scale the standard-deviation units
by k, chosen by maximum likelihood on all contract-snapshots in the window) separately for SPX, NDX and BTC. The three
values of k are committed as `research/layer16_k.json` the same day, before any December data is looked at. Layer 16
(drafted before 2026-12-01) applies them live to a shadow options probability from 2026-12-01 to 2027-02-26 and asks
whether the rescaled options beat both raw options and Kalshi's mid on Brier score. No other form of correction (beta
map, regime-conditional k) is tried in layer 16; those are reported here as exploratory only.

## Prediction, written so it can be wrong

Bitcoin options too wide (b > 1, interval above 1). Kalshi Bitcoin roughly calibrated at under 6 hours. Index options:
no detectable miscalibration in 8 weeks (too few independent days). Fitted k below 1 for Bitcoin (about 0.7).

## Ledger

Rules 1 and 2 enter `research/ledger_claims.csv` as L15a-c (options: SPX, NDX, BTC) and L15d-f (Kalshi) when decided.
