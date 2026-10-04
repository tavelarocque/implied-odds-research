"""The one holdout test of the Nasdaq-100 long-shot rule. Rule and pass bar: research/PREREGISTRATION.md (addendum).

Run once from the project root:  UNLOCK_HOLDOUT=1 python3 research/holdout_longshot.py
It reads only data from FINAL_TEST_START onward, the period no other analysis has used.
"""
import gzip, json, math, os, sys
from datetime import datetime

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import FINAL_TEST_START, HOLDOUT_UNLOCKED

if not HOLDOUT_UNLOCKED:
    sys.exit("This is the single holdout test. Run it with UNLOCK_HOLDOUT=1, once, and record the result.")

SERIES, H = "KXNASDAQ100", 1
MAX_STALENESS_H, MAX_SPREAD, MAX_MID, FEE_RATE = 1.0, 0.10, 0.02, 0.07
HIST = os.path.join(ROOT, "data", "history", "kalshi")
OUT = os.path.join(ROOT, "research", "output", "holdout_longshot")
os.makedirs(OUT, exist_ok=True)
rng = np.random.default_rng(2026)


def read_jsonl(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(l) for l in f]


def dollars(block, field="close"):
    """Same three-format parser as calibration.py."""
    if block is None:
        return np.nan
    raw = block.get(f"{field}_dollars")
    if raw in (None, ""):
        raw = block.get(field)
        if raw in (None, ""):
            return np.nan
        if not isinstance(raw, str):
            return float(raw) / 100
    return float(raw)


assert dollars({"close_dollars": "0.12"}) == 0.12 and dollars({"close": "0.1200"}) == 0.12 and dollars({"close": 12}) == 0.12

mk = pd.DataFrame(read_jsonl(os.path.join(HIST, f"markets_{SERIES}.jsonl.gz")))
mk = mk[mk["result"].isin(["yes", "no"])].copy()
mk["y"] = (mk["result"] == "yes").astype(int)
mk = mk[mk.groupby("event_ticker")["y"].transform("sum") == 1].copy()
mk = mk[mk.close_time.str[:10] >= FINAL_TEST_START].copy()            # holdout only
mk["close_ts"] = mk.close_time.map(lambda s: int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()))
print(f"holdout: {len(mk):,} settled contracts over {mk.event_ticker.nunique()} trading days "
      f"({mk.close_time.min()[:10]} to {mk.close_time.max()[:10]})")

rows = []
for m in mk.itertuples():
    p = os.path.join(HIST, "candles_60m", SERIES, f"{m.ticker}.json.gz")
    if not os.path.exists(p):
        continue
    with gzip.open(p, "rt", encoding="utf-8") as f:
        cs = json.load(f)["candlesticks"]
    if not cs:
        continue
    t = np.array([c["end_period_ts"] for c in cs])
    target = m.close_ts - H * 3600
    i = np.searchsorted(t, target, side="right") - 1
    if i < 0 or target - t[i] > MAX_STALENESS_H * 3600:
        continue
    bid, ask = dollars(cs[i].get("yes_bid")), dollars(cs[i].get("yes_ask"))
    rows.append({"ticker": m.ticker, "event": m.event_ticker, "date": m.close_time[:10], "bid": bid, "ask": ask, "y": m.y})

q = pd.DataFrame(rows)
q = q[(q.bid > 0) & (q.ask < 1) & (q.ask > q.bid) & (q.ask - q.bid <= MAX_SPREAD)].copy()
q["mid"] = (q.bid + q.ask) / 2
assert 0.005 < (q.ask - q.bid).median() < 0.2, "price units look wrong"
q = q[q.mid <= MAX_MID].copy()

q["pnl"] = q.bid - q.y - FEE_RATE * q.bid * (1 - q.bid)
# Kalshi rounds the fee up to a cent per order; for an order of 100 contracts that is ceil(100 * fee) / 100 each.
q["pnl_rounded"] = q.bid - q.y - q.bid.map(lambda b: math.ceil(round(100 * FEE_RATE * b * (1 - b) * 100, 6)) / 100 / 100)
q.to_csv(os.path.join(OUT, "trades.csv"), index=False)

codes, uniq = pd.factorize(q.event)
boot = []
for _ in range(2000):
    w = np.bincount(rng.integers(0, len(uniq), len(uniq)), minlength=len(uniq))[codes]
    boot.append(np.average(q.pnl, weights=w) if w.sum() else np.nan)
lo, hi = np.nanpercentile(boot, [2.5, 97.5])
mean = q.pnl.mean()
passed = lo > 0

daily = q.groupby("date").pnl.sum()
print(f"\nqualifying contracts: {len(q)} over {q.event.nunique()} trading days; settled YES: {int(q.y.sum())}")
print(f"PRIMARY  mean profit per contract: {100 * mean:+.3f} cents  95% interval [{100 * lo:+.3f}, {100 * hi:+.3f}]")
print(f"         -> {'PASS: the rule made money out of sample' if passed else 'FAIL: no reliable profit out of sample'}")
print(f"also     with the fee rounded up per 100-contract order: {100 * q.pnl_rounded.mean():+.3f} cents per contract")
print(f"also     one contract of each qualifying range per day: mean {100 * daily.mean():+.2f} cents/day, "
      f"worst day {100 * daily.min():+.2f}, best day {100 * daily.max():+.2f}, {len(daily)} days")
print(f"for comparison, the pre-holdout estimate was +0.72 cents [0.13, 0.93] on 473 contracts")
pd.DataFrame([{"n": len(q), "days": q.event.nunique(), "yes": int(q.y.sum()), "mean_cents": 100 * mean,
               "lo_cents": 100 * lo, "hi_cents": 100 * hi, "rounded_fee_cents": 100 * q.pnl_rounded.mean(),
               "passed": passed}]).to_csv(os.path.join(OUT, "result.csv"), index=False)
