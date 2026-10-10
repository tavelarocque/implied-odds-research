# Pre-registered: layer 13b, trading toward the layer 13 blend on Kalshi's 5pm Bitcoin sets (live paper)

Written 2026-10-10, after layer 13's holdout test (README) and before any live layer 13b decision exists. The git
commit that adds this file, with `live_l13` in `trade/paper.py`, is the timestamp.

## Why

Layer 13 passed on the holdout at 3 hours: the frozen blend logit P = 0.846 logit(Kalshi mid) + 0.432
logit(lognormal) beat Kalshi's price (Brier -0.0017, 97.5% interval -0.0027 to -0.0005). Its pre-registered trading
description, on hourly candle quotes, made +5.7 cents per contract (+2.0 to +9.3) over 414 trades on 126 days. Candle
quotes are not fills. This layer trades the same rule on the live order book, every day, to see whether it survives
real quotes, real timing and the fee.

## The rule (trade/paper.py, `live_l13`)

- **When:** the one crypto snapshot 2.5 to 3.5 hours before the 5pm ET KXBTCD set settles (the snapshot layer 11's
  live test uses). One evaluation per set.
- **Lognormal:** Coinbase BTC-USD hourly candles fetched at decision time; S = close of the last completed hour;
  sigma = standard deviation of the 23 hourly log returns in the last 24 completed hours, times the square root of
  the hours from that close to settlement; zero drift; P = N(ln(S/K) / sigma). If Coinbase does not return 24
  consecutive completed hours ending at the last full hour, the set is logged as not evaluated and not traded.
- **Contracts:** every "greater" strike of that set within 6% of S, yes bid > 0, a live ask below $1, spread at most
  10 cents; Kalshi mid = (bid + ask) / 2 from the snapshot's order book.
- **Blend (layer 13, frozen, 3-hour coefficients):** logit P = 0.846 logit(mid) + 0.432 logit(lognormal),
  probabilities clipped to 0.5%-99.5% inside the logits.
- **Trade:** buy 100 YES at the ask if P - ask - fee > 3 cents; sell 100 YES at the bid if bid - P - fee > 3
  cents; fee = Kalshi's taker fee 0.07 x price x (1 - price) rounded up per 100 contracts. Held to settlement.
  Results from Kalshi's API (`data/raw/paper_l13_results/`), every trade and its win or loss in the morning digest.

## The verdict

Sets settling 2026-10-10 to 2027-01-31, analysed once on or after 2027-02-01.

- Profit per contract after fees, averaged over trades, with a 95% interval from 2,000 resamples of whole settlement
  days.
- **Edge** if at least 40 trades on at least 20 days and the interval's lower end is above 0.
- **No edge** if the interval's upper end is below 0.
- **Inconclusive** otherwise.
- Reported alongside, not part of the verdict: win rate; profit by side (bought vs sold YES); trades where the book
  showed at least 100 contracts at the price vs fewer; capital tied up and the worst day; the same rule replayed on
  Kalshi's hourly candles for the same sets (layer 13 test B's quotes), to measure what live quotes cost against
  candle quotes.

## Prediction, written so it can be wrong

Edge or inconclusive with a positive mean, smaller than the holdout's +5.7 cents (live quotes are taken a few minutes
after the hour, and the displayed size is often under 100 contracts on the far strikes).

## Limits

Paper trades assume the displayed touch fills 100 contracts; the book sizes are logged so this can be checked. It
overlaps layer 11 (both buy expensive favourites 3 hours out), so the two are not independent evidence. Nothing in the
rule changes after the first trade is logged.
