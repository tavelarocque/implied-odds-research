# Pre-registered: layer 5s, does layer 5's Bitcoin edge live only on the "smaller move" side?

Written 2026-10-14 (PT). Registered by the commit that adds this file, which must land before 2026-10-15 06:00 UTC
(2026-10-14 23:00 PT). Layer 5 and its 2026-11-30 verdict are unchanged: same rule, same trades, same paper log. This
layer only labels layer 5's future Bitcoin trades and tests a split of them. It places no trades of its own.

## Where the idea came from (stated so nobody mistakes it for evidence)

Found after the fact on 2026-10-14, by looking at layer 5's 560 settled Bitcoin paper trades from 2026-10-09 to
2026-10-14 during a drawdown (`research/explore_btc_wings.py`). Trades that bet Bitcoin would end *farther* from spot than Kalshi
priced lost $628 in total; trades betting it would end *closer* made $1,072. Before 2026-10-14 03:00 UTC the split was
+$259 vs +$1,354; after it, -$888 vs -$282. That is one look at five correlated days, chosen because it looked
interesting, so it is a hypothesis, not a result. None of those trades count below. Even on those trades the split is not significant: stay mean $3.32 per trade, 95% [-0.23, +8.12]; stay minus move $5.97, 95% [-0.77, +10.08] (`python research/layer5s.py --check`).

The mechanism it would fit: option-implied distributions carry the variance risk premium and so are too wide (the
reason for layers 15 and 16). When options put more probability than Kalshi on Bitcoin ending far from spot, the
options may be the biased side. If so, layer 5's edge should come from the opposite trades.

## Label, fixed now

Every layer 5 Bitcoin paper trade (KXBTCD "above K", hourly and daily, exactly as `trade/paper.py` logs them) with
strike K, spot S (the `spot` field logged with the trade) and side:
- **move** (a bet on a bigger move): buy with K > S, or sell with K < S;
- **stay** (a bet on a smaller move): buy with K < S, or sell with K > S.
(Kalshi strikes end in .99, so K = S does not occur; if it ever does, the trade is labelled stay.)

P&L per trade is layer 5's own: 100 contracts at the logged price, Kalshi's fee, settled on Kalshi's result
(`paper.pnl_of`).

## Data

Layer 5 Bitcoin trades with snapshot time from 2026-10-15 06:00 UTC up to (not including) 2026-11-08 00:00 UTC,
settled. Day = UTC date of the snapshot. If fewer than 300 stay trades or fewer than 15 distinct days have settled by
the readout, the window extends on the same rules to 2026-11-28 00:00 UTC and is read with layer 5 on 2026-11-30.

## Tests, read on 2026-11-09 (fixed now)

All intervals: 95%, 2,000 bootstrap resamples of whole UTC days, seed 515.

- **H1 (primary):** mean P&L per stay trade > 0.
- **H2:** mean P&L per stay trade minus mean P&L per move trade > 0.
- **H3 (secondary):** mean P&L per move trade < 0.

## Reading rule (fixed now)

- **"Stay-side edge confirmed"** if H1's interval is entirely above 0 *and* H2's interval is entirely above 0. A
  stay-only version of layer 5 then counts as a layer that has passed its verdict, so it becomes eligible for the
  real-money rule, subject to layer 5x's execution evidence.
- **"No split"** if H1 is above 0 but H2's interval includes 0: layer 5 works on both sides, and the 2026-10-14 split
  was noise.
- **"Not confirmed"** otherwise.
- H3 is reported with its interval and does not change the label.

Reported alongside, descriptive only, not deciding anything: totals and win rates by label; hourly vs daily; distance
|K/S - 1| in thirds; and layer 5x's execution-adjusted P&L for stay and move trades where requotes exist.

## Ledger

H1 and H2 enter `research/ledger_claims.csv` as L5Sa and L5Sb when decided.

## Fixed

These rules do not change after the first labelled trade. Bugs that make `research/layer5s.py` disagree with this
file are fixed to match this file, and noted here with the date.
