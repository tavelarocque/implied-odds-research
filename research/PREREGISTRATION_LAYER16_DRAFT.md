# DRAFT, not registered: layer 16, does passive liquidity in Kalshi's Bitcoin contracts pay?

**Status: draft written 2026-10-17 by the assistant at Tave's request; data section revised the same day to
backfilled trades and prices after the first live day lost an hour to the Mac sleeping. It registers nothing until Tave edits it,
renames it to `PREREGISTRATION_LAYER16.md` and commits it.** That commit is the timestamp, and it must land before
any high-frequency data from the test window below is compared with option fair values. No such comparison has been
made.

## Question

Layer 5 asks whether Kalshi's BTC prices agree with the options market. This asks the market maker's question:
when someone trades in a near-the-money KXBTCD contract, who is better informed, the taker or whoever was resting
the quote? The measure is the **markout**: a trade's profit to the passive side, marked against the options-implied
fair value some time later.

For a taker who buys YES at price P, the resting seller's markout at horizon h is P - V(t + h), where V is the fair
value h after the trade; for a taker who sells YES at P, it is V(t + h) - P. Averaged over trades, a positive
markout means passive quotes earn more than they lose to informed flow; a negative one means takers are informed
enough to beat the spread.

V comes from the OCaml contracts project (`~/CODE/contracts`, `Markout`): the latest hourly Deribit smile for the
event (`tools/export_hf_for_ocaml.py --source backfill`), moved by the BTC price's own change since that snapshot
(sticky moneyness; one price series at both ends, so a level difference between Kraken and Deribit's index cancels)
and shortened to the time left (constant vol), priced through the contract language. It is risk-neutral, so it carries
the volatility risk premium, which tilts the markout at long horizons; the primary horizon is short for that reason.

## Data and dates

- **Trades and prices: backfilled after settlement** (`collect/kalshi_trades_backfill.py`, weekly). Kalshi keeps
  each market's full trade history; Kraken's XBT/USD trade history gives the last BTC price each second. Markets:
  KXBTCD "above" contracts within 2% of the Coinbase price one hour or 24 hours before the close (chosen without the
  settled price). Nothing has to stay running, so the sample has no gaps from a machine sleeping.
- **Quotes (optional, descriptive only):** `collect/kalshi_hf.py`, top of book every 5 seconds while a machine runs
  it. Only the quote replay needs them; the verdict does not.
- **Smiles:** the hourly Deribit snapshots the cloud workflow already collects (`tools/export_for_ocaml.py`).
- **Development:** trades from 2026-10-17 to 2026-11-27. They lie inside layer 5's window (Kalshi BTC contracts
  settling 2026-10-10 to 2026-11-27), so they are not compared with option fair values before 2026-11-30; the OCaml
  tool refuses to. Before then the method is developed on synthetic data only.
- **Test window:** trades from 2026-11-28 to 2026-12-27 inclusive (UTC), outside layer 5's window. The analysis runs
  once, on or after 2026-12-28.
- **Trades used:** strike within 1% of the BTC price at the trade (|ln(strike / price)| <= 0.01), at least 15 minutes
  and at most 24 hours before close, a fair value available (smile less than 75 minutes old, BTC price less than 30
  seconds old), and a trade price between 5 and 95 cents.

## Decision rule

Primary: the volume-weighted mean passive-side markout at h = 60 seconds, in cents per contract, with a 95% interval
from 2,000 bootstrap resamples of whole events (trades in the same event are not independent).

- **Passive liquidity pays** if there are at least 2,000 trades on at least 20 days and the interval is above 0.
- **Takers are informed** if the interval is below 0.
- Otherwise **inconclusive**.

## Also reported, not part of the verdict

- Markouts at 0 (the half-spread paid), 10 seconds, 5 minutes and at the close (V at the close is the settlement
  value from the index; Kalshi settles on the CF Benchmarks BRTI, so this is approximate).
- Split by time to close (15-60 minutes, 1-6 hours, 6-24 hours), by distance from the money, by taker side, and
  by trade size.
- The OCaml `Market_maker` quoting rule replayed against the real book and trade prints, assuming its quote is
  filled whenever a trade prints at or through it (optimistic about queue position; stated as such).

## Known limitations, stated in advance

- Kraken's last trade in a second stands in for BTC's price; in a second without a Kraken trade the previous one is
  used (at most 30 seconds old, or the trade is dropped). Markouts shorter than about 10 seconds are not meaningful.
- The quote collector runs only while its machine is awake; the replay reports its gaps. The verdict doesn't use it.
- V is a model value. A negative markout can mean takers are informed, or that V lags the market (the smile is up
  to an hour old; only the index moves it in between).
