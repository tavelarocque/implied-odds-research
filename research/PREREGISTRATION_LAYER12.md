# Pre-registered: layer 12, Kronos (a pretrained candlestick model) as a forecaster of Kalshi's 5pm Bitcoin contracts

Written 2026-10-09, before Kronos has been run on any project data and before any result below has been computed. The
git commit that adds this file, and `research/test_layer12_kronos.py` with it, is the timestamp.

## Why, and what is being tested

Kronos (Shi et al., Tsinghua, AAAI 2026; arXiv 2508.02739; github.com/shiyu-coder/Kronos, MIT licence) is a
decoder-only transformer pretrained on about 12 billion candlesticks from 45+ exchanges, crypto included. It turns
each candle into tokens and forecasts by sampling future candles, so it gives a distribution of where Bitcoin will
be, not just a point. The paper's own numbers are modest (RankIC about 0.025) and there is no independent check.

This layer asks the project's usual question of it: is its probability for "BTC above K at 5pm ET" better than
Kalshi's price, and does it know anything Kalshi's price does not? It is a forecasting test, not a trading rule.

## The model, fixed

- Kronos-small (24.7M parameters) with Kronos-Tokenizer-base, from Hugging Face `NeoQuasar`, code at Kronos commit
  `67b630e67f6a18c9e9be918d9b4337c960db1e9a`. Context 512 candles. The repository's default sampling settings:
  temperature T = 1.0, top_p = 0.9, top_k off. Run on CPU, torch seed 12.
- Input: Coinbase BTC-USD hourly candles (`data/history/crypto/coinbase_1h.csv`; open, high, low, close, volume;
  "amount" = volume x mean price, as Kronos fills it), the 512 hourly candles that have fully closed by the quote
  time. Timestamps in UTC.
- Output: 200 independent sample paths (200 copies of the series through `predict_batch` with sample_count = 1, so
  the repository's averaging over samples never runs), each `h` hourly candles long, the last one ending at
  settlement. Kronos's probability for a strike K = share of paths whose final close is above K. One set of paths per
  settlement day and horizon, shared by every strike that day.
- Nothing is tuned: no fine-tuning, no other model size, no other temperature, no calibration of its output.

## The contracts (development data only; the locked holdout is not touched)

- Kalshi's 5pm ET Bitcoin sets (KXBTCD, events ending in 17, "greater" strikes, open at least 2 hours before they
  settle, settled yes or no), settling **2025-09-01 to 2026-03-31**. That window starts a month after Kronos's paper
  and ends before the project's holdout (2026-04-01), so the model cannot have been trained on it and the holdout stays
  closed. 212 settlement days.
- Horizons h = 1 and 3 hours before settlement (layer 11's). Kalshi's quote: the last hourly candle ending at or before
  the quote time and within an hour of it; yes bid > 0, ask < 1, ask > bid, spread at most 10 cents; Kalshi's
  probability = the mid.
- Strikes: every strike within 6% either side of the Coinbase close of the last completed hour at the quote time,
  i.e. chosen with information available then. Candles for strikes in that band that `collect/kalshi_btc_daily.py`
  had not downloaded (it chose strikes near the settled price, see layer 11's amendment) were filled by
  `FILL_ABOVE=1 FILL_FROM=2025-09-01 python3 collect/kalshi_btc_fill.py` before this test was run.

## Primary test (the verdict)

For each horizon, the mean over contracts of Brier(Kronos) - Brier(Kalshi mid), with a 97.5% interval from 2,000
resamples of whole settlement days (97.5% = a Bonferroni split of 5% over the two horizons).

- **Kronos beats Kalshi** at a horizon if the whole interval is below 0.
- **Kalshi beats Kronos** if the whole interval is above 0.
- **No difference shown** otherwise.
- Layer 12 **passes** if Kronos beats Kalshi at either horizon.

The prediction, written so it can be wrong: Kalshi beats Kronos at both horizons. Kronos sees only Bitcoin's own
price history; Kalshi's traders see that and everything else, and the project's own spot-price model already lost to
Kalshi (Brier 0.129 vs 0.125 on hourly sets).

## Secondary (reported, not part of the verdict)

1. **Market efficiency: does Kalshi's price already contain what Kronos sees?** Logistic regression of the outcome
   on logit(Kalshi mid) and logit(Kronos probability), both clipped to 0.5%-99.5%, per horizon. The Kronos
   coefficient with a 95% day-bootstrap interval. Above 0 with the interval clear of 0 would mean Kalshi's price
   leaves information in a public price history on the table, which a weak-form efficient market should not.
2. **By efficiency ratio:** secondary 1 split by the Bitcoin efficiency ratio of the 24 hours before the quote,
   |last close - first open| / (highest high - lowest low) over those 24 hourly candles, below vs above its median
   over the window's settlement days (median of the inputs only, no outcomes). The idea being checked: a
   pattern-reading model should do best when the market is trending cleanly (high ratio) and worst when it is choppy.
3. Description: Brier and its CORP decomposition (miscalibration, discrimination, uncertainty) for Kronos, Kalshi
   and a plain lognormal benchmark (volatility from the 24 hourly log returns before the quote, zero drift); Kronos's
   spread of final prices vs the realized move.

## Afterwards

- The primary result and secondary 1 each go in `research/ledger_claims.csv` (two horizons each, four rows) and in
  the README, whatever they are.
- If layer 12 passes, or secondary 1 is positive at a horizon, Kronos's probabilities are logged live (no trades) and
  the same primary statistic is tested once on 5pm sets settling 2026-10-15 to 2027-01-31, analysed on or after
  2027-02-01. If neither, Kronos is dropped from the project.

Nothing above changes after the results are seen.
