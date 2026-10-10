# Pre-registered: layer 11, selling Kalshi's downside Bitcoin long shots when the crowd is bearish

Written 2026-10-09, after the exploratory run on the development sample (README, layer 11) and before any Kalshi
Bitcoin data from 2026-04-01 onward has been downloaded or looked at. The git commit that adds this file is the
timestamp. Two tests follow from it: one run on the locked holdout, and a live forward test.

## The rule

- **Contracts:** Kalshi's 5pm ET Bitcoin sets (series KXBTCD, events ending in 17, open at least 2 hours before they
  settle). Every "BTC above K" contract in the set.
- **Signal day:** a settlement day on which either
  - the Crypto Fear & Greed Index (alternative.me), stamped 00:00 UTC of that day, is 25 or below; or
  - the mean Binance BTCUSDT funding rate over the 24 hours ending 6 hours before settlement is 0.0000149 per 8 hours
    or below (the bottom fifth of the development sample, fixed here as a number).
- **Trade:** 3 hours before settlement, every contract whose yes bid and ask are both quoted, with a spread of at most
  10 cents and a mid of 90 cents or more (its NO side is a downside long shot priced at 10 cents or less). Buy 1 YES at
  the ask (equivalently, sell the long shot) and hold to settlement. Kalshi's taker fee, 0.07 x P x (1 - P), rounded
  up per 100-contract order, as in layer 5. One trade per contract.
- **Also reported, not part of the verdict:** the same at 1 hour before settlement; the two signals separately; the
  non-signal days (expected: about zero).

## The verdict: on the loss rate, not on a bootstrap of the mean

The development sample showed why: with a 0.9% loss rate, a bootstrap of mean profit has almost nothing to vary and
its interval looks far tighter than the evidence is (the same failure as the S&P long-shot holdout, README).

- **Break-even loss rate** p* = the mean over trades of (1 - ask - fee): the fraction of trades that may lose before the
  rule loses money. About 2.7% at the development sample's prices.
- **Edge** if there are at least 40 trades on at least 20 signal days and the exact (Clopper-Pearson) one-sided 95%
  upper bound on the loss rate is below p*, counting both per trade and per signal day (a day with any loss counts as
  a losing day), so that losses clustering on one bad day cannot hide.
- **No edge** if the one-sided 95% lower bound on the per-trade loss rate is above p*.
- **Inconclusive** otherwise. Mean profit per contract with a day bootstrap is reported alongside, as a description.

## Test A: the holdout (run once, on 2026-10-09 or 10)

Sets settling 2026-04-01 to 2026-09-30, which `research/config.py` has reserved since 2026-10-03. Data downloaded only
after this file is committed, with the same tools as the development sample (`collect/kalshi_btc_daily.py`,
`collect/crypto_sentiment.py`); run with `UNLOCK_HOLDOUT=1`, once, and the result goes in the README whatever it is.
The development sample had a signal on about 30% of days, so the holdout should hold about 50 signal days.

## Test B: live, forward

Sets settling 2026-10-10 to 2027-01-31, from the live crypto snapshots (`data/raw/kalshi_crypto/`, hourly at :07):
the snapshot nearest 3 hours before settlement and within 30 minutes of it. Fear & Greed and funding taken from their
histories afterwards, exactly as defined above. Analysed once, on or after 2027-02-01.

## Known limitations

- Fear days cluster in time (most of the development sample's fell in November 2025 to March 2026, a falling market),
  so the holdout and the forward window may hold few of them or one long run of them.
- Development-sample prices came from hourly candles; the live test uses snapshots. Both read the touch.
- One finding out of ten comparisons. The prediction, written down so it can be wrong: the holdout verdict is
  "inconclusive" or "edge", mean profit is positive, and non-signal days stay near zero.
Nothing in the rule changes after the results are seen.

## Amendment, 2026-10-09 (before test A was run; no holdout result had been computed or seen)

A data-selection flaw was found while reading Kapoor & Narayanan (2022) on leakage: `collect/kalshi_btc_daily.py`
downloaded candles only for strikes within 4% of the *settled* price, which uses the outcome to choose the sample. If
Bitcoin fell more than about 4% in the last hours, the downside long shots that then paid out were never downloaded,
so the test could not see those losses (development sample: at most 3 such contracts at 3 hours, none at 1 hour;
`research/check_strike_selection.py`). Fix, decided before any holdout outcome was looked at: `collect/kalshi_btc_fill.py`
adds candles for every strike within 6% below the Bitcoin price 1 or 3 hours before settlement (Coinbase hourly), a
selection known at decision time. Test A runs on the combined data. The rule, thresholds and verdict are unchanged.
