"""Layer 11, test A: the rule pre-registered in research/PREREGISTRATION_LAYER11.md, run once on the holdout.

    UNLOCK_HOLDOUT=1 python3 research/test_layer11.py
Contracts settling 2026-04-01 to 2026-09-30 only. Nothing here is tuned; thresholds come from the pre-registration.
"""
import gzip, json, os, sys
import numpy as np
import pandas as pd
from scipy.stats import beta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research"))
from config import HOLDOUT_UNLOCKED
import explore_btc_sentiment as X

WINDOW = ("2026-04-01", "2026-09-30")
FG_MAX, FUND_MAX = 25, 0.0000149
rng = np.random.default_rng(111)


def cp_upper(k, n):          # exact one-sided 95% upper bound
    return 1.0 if n == 0 else (1.0 if k >= n else beta.ppf(0.95, k + 1, n - k))


def cp_lower(k, n):
    return 0.0 if k == 0 else beta.ppf(0.05, k, n - k + 1)


def load_markets():
    keep = []
    for l in gzip.open(os.path.join(X.KH, "markets_KXBTCD_5pm.jsonl.gz"), "rt"):
        m = json.loads(l)
        day = m["close_time"][:10]
        if not (WINDOW[0] <= day <= WINDOW[1]) or not m["event_ticker"].endswith("17"):
            continue
        if m.get("strike_type") != "greater" or m.get("result") not in ("yes", "no"):
            continue
        close, opened = pd.Timestamp(m["close_time"]), pd.Timestamp(m.get("open_time") or m["close_time"])
        if close - opened < pd.Timedelta(hours=2):
            continue
        keep.append({"ticker": m["ticker"], "event": m["event_ticker"], "close": close, "k": float(m["floor_strike"]),
                     "y": 1.0 if m["result"] == "yes" else 0.0})
    return pd.DataFrame(keep)


def main():
    if not HOLDOUT_UNLOCKED:
        sys.exit("Holdout test: run once with UNLOCK_HOLDOUT=1, and record the result in the README.")
    mk = load_markets()
    q = X.quotes(mk)
    q = q[q.side == "down"].copy()                       # mid >= 90c: the NO side is the long shot
    m = X.mood(q.groupby("day").close.first())
    q = q.join(m, on="day")
    q["signal"] = (q.fg <= FG_MAX) | (q.funding <= FUND_MAX)
    q["fee"] = X.fee(q.ask)
    q["pnl"] = q.y - q.ask - q.fee                       # buy YES at the ask
    q["lost"] = q.y == 0
    print(f"Holdout {WINDOW[0]} to {WINDOW[1]}: {mk.event.nunique()} 5pm sets; signal days "
          f"{q[q.signal].day.nunique()} of {q.day.nunique()} days with a quoted downside long shot")
    for h, label in ((3, "PRIMARY, 3 hours before"), (1, "reported, 1 hour before")):
        for name, sel in (("signal days", q.signal), ("non-signal days", ~q.signal)):
            s = q[(q.h == h) & sel]
            if s.empty:
                print(f"  {label}, {name}: no trades"); continue
            n, k = len(s), int(s.lost.sum())
            days = s.groupby("day").lost.any()
            nd, kd = len(days), int(days.sum())
            pstar = (1 - s.ask - s.fee).mean()
            g = s.groupby("day").pnl.agg(["sum", "count"]).values
            w = rng.multinomial(len(g), np.full(len(g), 1 / len(g)), size=2000) @ g
            lo, hi = np.percentile(w[:, 0] / w[:, 1], [2.5, 97.5])
            line = (f"  {label}, {name}: {n} trades on {nd} days; long shot paid on {k} ({k / n:.1%}), "
                    f"days with a loss {kd}; break-even loss rate {pstar:.2%}; upper bound per trade "
                    f"{cp_upper(k, n):.2%}, per day {cp_upper(kd, nd):.2%}; lower bound per trade {cp_lower(k, n):.2%}; "
                    f"mean {100 * s.pnl.mean():+.2f}c per contract ({100 * lo:+.2f} to {100 * hi:+.2f})")
            if h == 3 and name == "signal days":
                enough = n >= 40 and nd >= 20
                v = ("EDGE" if enough and cp_upper(k, n) < pstar and cp_upper(kd, nd) < pstar else
                     "NO EDGE" if cp_lower(k, n) > pstar else "INCONCLUSIVE")
                line += f"\n  VERDICT: {v}" + ("" if enough else " (fewer than 40 trades or 20 signal days)")
            print(line)
    q.to_csv(os.path.join(ROOT, "research", "output", "layer11_holdout.csv"), index=False)


if __name__ == "__main__":
    main()
