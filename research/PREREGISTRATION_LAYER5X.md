# Pre-registered: layer 5x, would layer 5's Bitcoin paper trades have filled? (no money)

Written 2026-10-13, before any requote data exists. The commit that adds this file and `trade/execcheck.py` is the
timestamp. Layer 5 and its 2026-11-30 verdict are unchanged and are judged on paper, as registered. This layer replaces
layer 5m (the real-money mirror) as the execution study, because no Kalshi account is available from BC; layer 5m's code
stays in the repo, off.

## Why

Layer 5's paper trader assumes 100 contracts fill at the quoted touch at the snapshot. A real order lands later (the
paper decision is ~15-30 s after the snapshot), and quotes can vanish. If the quotes that vanish are the ones that carry
the edge, the paper result overstates what anyone could earn. This measures that without placing orders.

## Design, fixed now

(A) Requote, live only. In the same run, immediately after layer 5 writes a new BTC paper trade, fetch that contract's
full public order book (`GET /markets/{ticker}/orderbook`; if refused, the public market touch, flagged as such) and
record `available` = contracts at the paper price or better (asks <= price for a buy, bids >= price for a sell), plus the
time since the snapshot. An immediate-or-cancel order for N contracts at the paper price is assumed to fill
min(N, available), for N in {2, 10, 100}. Unfilled contracts are not traded (no walking the book).

(B) Prints. At least 15 minutes after the snapshot, pull the public non-block trade prints on that contract from 300 s
before to 600 s after the snapshot. Class per trade: **confirmed** if a taker traded in our direction (bought YES for a
buy, bought NO for a sell) at our price or better within 120 s after the snapshot; **moved** if prints in our direction
within 120 s exist only at worse prices; **quiet** otherwise. Runs over every layer 5 BTC paper trade since 2026-10-09,
backfill included, at most 60 per run. A quiet trade with zero prints in the whole window is reported as "no data".

Fees: Kalshi's taker fee, ceil(0.07 * p * (1 - p) * N * 100) cents per order, the same formula as layer 5.

## Readout, 2026-11-30, with layer 5 (fixed now)

Sample: requoted trades settled by 2026-11-30. If fewer than 100, the readout moves to the first day with 100, no later
than 2027-02-01; if still fewer, report as underpowered and draw no conclusion.

1. Fill rate at N = 2, 10, 100: share of trades filled in full, and contracts filled / contracts offered.
2. Execution-adjusted P&L at each N (fills as in A, fees as above) and the ratio R(N) = execution-adjusted P&L / paper
   P&L at the same N. Day-block bootstrap (2,000 resamples, as layer 5) 90% interval for mean execution-adjusted P&L per
   trade.
3. Selection check: mean paper P&L per contract on trades with available >= 100 vs available < 100, difference with a
   day-block bootstrap 90% interval.
4. Prints (B): share confirmed / moved / quiet / no data, and settled paper P&L by class.

Reading rule:
- "Layer 5's BTC edge survives execution at size N" if R(N) >= 0.5 and the 90% interval in (2) is above 0.
- "Adverse selection" if the selection check's interval excludes 0 with the available < 100 group ahead; then the
  paper P&L is reported as overstated, whatever (2) says.
- "Quote artifact" if R(2) < 0.5.
- Prints are supporting evidence only and cannot overturn (A).

## Not in the multiple-testing ledger

This tests no new edge; it qualifies layer 5's. It adds no hypothesis to the BHY ledger.

## Fixed

These rules do not change after the first requote is logged. Bugs that make the code disagree with this file are fixed
to match this file, and noted here with the date.
