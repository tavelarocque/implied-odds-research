"""DIAGNOSTIC (data validity, not a result): how are Polymarket's prices-history timestamps aligned with real time?

For each Polymarket 10-minute point (t_i, p_i), compare its change since the previous point with Kalshi's change over
the same window shifted by d minutes, for d from -20 to +10. A correctly stamped series peaks near d = 0 (two venues on
the same index, linked by arbitrage). A peak at d = -10 means each Polymarket price describes the window ending 10
minutes before its stamp.

Run from the project root:  python3 research/diag_poly_timing.py [spx|ndx] [n_days]
"""
import gzip, json, os, re, sys
from datetime import datetime
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "research"))
from implied import make_ladder, prob_above
from config import exploratory

INDEX = sys.argv[1] if len(sys.argv) > 1 else "spx"
N_DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else 40
SERIES, KIND = {"spx": ("KXINX", "close"), "ndx": ("KXNASDAQ100", "ndx_close")}[INDEX]
KH, PH = os.path.join(ROOT, "data", "history", "kalshi"), os.path.join(ROOT, "data", "history", "polymarket")
rd = lambda p: [json.loads(l) for l in gzip.open(p, "rt")]
ts = lambda s: int(datetime.fromisoformat(re.sub(r"\.\d+", "", s.replace("Z", "+00:00"))).timestamp())
money = lambda x: None if x in (None, "") else float(str(x).replace(",", ""))

mk = pd.DataFrame(rd(os.path.join(KH, f"markets_{SERIES}.jsonl.gz")))
mk = mk[mk.result.isin(["yes", "no"])]; mk["day"] = mk.close_time.str[:10]
days = mk.groupby("day").agg(event=("event_ticker", "first"), close_time=("close_time", "first"),
                             settle=("expiration_value", lambda s: next((money(v) for v in s if v), None))).sort_index()
days["K"] = days.settle.shift(1)
pm = pd.DataFrame(rd(os.path.join(PH, "events.jsonl.gz")))
pm = pm[(pm.kind == KIND) & pm.rules.str.contains("prior trading day", case=False, na=False)]
pm = pm[exploratory(pm.date) & pm.date.isin(days.index)].sort_values("date").head(N_DAYS)

OFFS = list(range(-20, 11))
acc = {d: ([], []) for d in OFFS}
for e in pm.itertuples():
    d = days.loc[e.date]
    if pd.isna(d.K):
        continue
    up = json.load(gzip.open(os.path.join(PH, "prices_10m", f"{e.slug}.json.gz"), "rt"))["history"].get("Up", [])
    lad_ms = mk[mk.event_ticker == d.event]
    C = {}
    for m in lad_ms.itertuples():
        cs = json.load(gzip.open(os.path.join(KH, "candles_1m", SERIES, f"{m.ticker}.json.gz"), "rt"))["candlesticks"]
        C[m.ticker] = (np.array([c["end_period_ts"] for c in cs]), cs) if cs else None
    def pk(target):
        q = []
        for m in lad_ms.itertuples():
            c, b = C.get(m.ticker), np.nan
            if c is not None:
                i = np.searchsorted(c[0], target, side="right") - 1
                blk = c[1][i]["yes_bid"] if i >= 0 else c[1][0]["yes_bid"]
                f = "close" if i >= 0 else "open"           # current API names it close_dollars; archived files close
                raw = blk.get(f"{f}_dollars", blk.get(f))
                b = (float(raw) if isinstance(raw, str) else float(raw) / 100) if raw not in (None, "") else np.nan
            q.append({"strike_type": m.strike_type, "floor_strike": m.floor_strike, "cap_strike": m.cap_strike,
                      "bid": 0.0 if b != b else b, "ask": np.nan})
        return prob_above(make_ladder(q), d.K, "bid")
    close = ts(d.close_time)
    pts = [(x["t"], x["p"]) for x in up if close - 6 * 3600 <= x["t"] <= close - 600]
    cache = {}
    for (t0, p0), (t1, p1) in zip(pts, pts[1:]):
        if not 400 <= t1 - t0 <= 800:
            continue
        for o in OFFS:
            a, b = t0 + 60 * o, t1 + 60 * o
            for x in (a, b):
                if x not in cache:
                    cache[x] = pk(x)
            dk = cache[b] - cache[a]
            if np.isfinite(dk):
                acc[o][0].append(p1 - p0); acc[o][1].append(dk)

print(f"{INDEX}: {len(pm)} days. Correlation of Polymarket's change between consecutive stamps with Kalshi's change over "
      f"the same window shifted by d minutes:")
for o in OFFS:
    x, y = np.array(acc[o][0]), np.array(acc[o][1])
    print(f"  d = {o:+3d} min   corr {np.corrcoef(x, y)[0, 1]:+.3f}   n = {len(x)}")
