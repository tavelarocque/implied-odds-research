# Pre-registered: layer 5m, does layer 5's Bitcoin edge survive real execution?

**Status 2026-10-13: dormant.** No Kalshi account (live or demo) is available from BC, so this layer never ran. `trade/mirror.py` stays in the repo and does nothing unless the GitHub variable KALSHI_LIVE or KALSHI_DEMO is "on". The execution question moved to layer 5x (research/PREREGISTRATION_LAYER5X.md), which needs no money. If access ever changes, this file applies as written from the date the mirror is switched on.

Written 2026-10-13, before the first real order. The commit that adds this file and `trade/mirror.py` is the timestamp.
Layer 5 and its 2026-11-30 verdict are unchanged and are judged on paper, as registered.

## Why

Layer 5's paper trader assumes 100 contracts fill at the quoted touch the moment the snapshot is taken. Real orders
arrive seconds later, can miss, and can move the price. Some quotes show only 1-2 contracts. This layer measures how
much of the paper result survives contact with the exchange. It is an execution study, not a new trading rule.

## Design, fixed now

- Every new layer 5 BTC paper trade (KXBTCD, hourly and daily) is copied to Kalshi as a 2-contract
  immediate-or-cancel limit order at the paper trade's own price, in the same run. Unfilled contracts are cancelled by
  the exchange and logged as misses. No order is ever placed at a worse price than the paper trade.
- Brakes, enforced in code: $200 starting bankroll; no new orders after -$25 realized on the day's trades; no orders
  at all after -$100 realized; worst-case open exposure capped at $60; a kill switch (GitHub variable KALSHI_LIVE).
  Trades skipped by a brake are logged with the reason and excluded from the matched comparison below.
- Demo exchange first (KALSHI_DEMO) to test order flow; demo fills are not part of the analysis.

## Analysis, on or after 2026-11-30, live fills from the first live order to 2026-11-27

1. **Fill rate (reported):** filled contracts / attempted, overall and by price paid (<10c, 10-50c, 50-90c, 90c+).
2. **Slippage (reported):** fill price minus paper price, in cents, signed so positive = worse for us. With IOC
   limits at the paper price it can only be <= 0 (price improvement) or a miss.
3. **Primary:** on matched trades (same ticker and snapshot, filled), mean P&L per contract of the real fills minus the
   paper trade's P&L per contract (both after their actual or modelled fees), 95% interval from 2,000 resamples of whole
   UTC days. **Execution erodes the edge** if the whole interval is below 0; otherwise **no detectable erosion**.
4. **Selection check (reported):** paper P&L per contract on the trades the mirror filled vs the trades it missed. If
   misses are disproportionately the winners, fills are adversely selected even with no slippage.

## Prediction, written so it can be wrong

Fill rate well below 100% on long shots and on thin books; no slippage by construction; no detectable erosion on
matched fills, but adverse selection (missed trades are the better paper trades) visible in rule 4.

## Not part of this layer

Sizing up, other layers, or any change to which trades are taken. Any of those would need its own pre-registration.
Ledger: L5m (rule 3) when decided. Real-money gains or losses are not research results and are reported separately.
