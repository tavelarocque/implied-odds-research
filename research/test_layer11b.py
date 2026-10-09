"""Layer 11b, test A: the rule pre-registered in research/PREREGISTRATION_LAYER11B.md, run once on the holdout.

    UNLOCK_HOLDOUT=1 python3 research/test_layer11b.py
Contracts settling 2026-04-01 to 2026-09-30 only. Run after research/test_layer11.py (it reuses that test's helpers and
the same data). Nothing here is tuned.
"""
import os, sys
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research"))
from config import HOLDOUT_UNLOCKED
import explore_btc_sentiment as X
import explore_regimes as R
import test_layer11 as T11

rng = np.random.default_rng(112)


def main():
    if not HOLDOUT_UNLOCKED:
        sys.exit("Holdout test: run once with UNLOCK_HOLDOUT=1, and record the result in the README.")
    d = pd.read_csv(os.path.join(ROOT, "data", "history", "crypto", "btc_daily.csv"), index_col=0, parse_dates=True)
    d = d[d.index <= T11.WINDOW[1]]
    f, p = R.walk_forward(d, 2, 2017)                                 # 2026 filtered with the fit on bars before 2026
    f.index = (f.index + pd.Timedelta(days=1)).strftime("%Y-%m-%d")   # day t's close -> settlement day t+1
    mk = T11.load_markets()
    q = X.quotes(mk)
    q = q[q.side == "down"].copy()
    q = q.join(X.mood(q.groupby("day").close.first()), on="day").join(f[["s1"]], on="day")
    q["signal"] = (q.fg <= T11.FG_MAX) | (q.funding <= T11.FUND_MAX)
    q["turb"] = q.s1 > 0.5
    q["fee"] = X.fee(q.ask)
    q["pnl"] = q.y - q.ask - q.fee
    q["lost"] = q.y == 0
    print(f"Holdout {T11.WINDOW[0]} to {T11.WINDOW[1]}: turbulent days {q[q.turb].day.nunique()} of {q.day.nunique()} "
          f"days with a quoted downside long shot; missing regime {int(q.s1.isna().sum())} quotes")
    for h, label in ((3, "PRIMARY, 3 hours before"), (1, "reported, 1 hour before")):
        for name, sel in (("turbulent days", q.turb), ("other days", ~q.turb),
                          ("turbulent, layer 11 signal", q.turb & q.signal), ("turbulent, no layer 11 signal", q.turb & ~q.signal)):
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
            line = (f"  {label}, {name}: {n} trades on {nd} days; long shot paid on {k} ({k / n:.1%}), days with a loss "
                    f"{kd}; break-even loss rate {pstar:.2%}; upper bound per trade {T11.cp_upper(k, n):.2%}, per day "
                    f"{T11.cp_upper(kd, nd):.2%}; lower bound per trade {T11.cp_lower(k, n):.2%}; mean "
                    f"{100 * s.pnl.mean():+.2f}c per contract ({100 * lo:+.2f} to {100 * hi:+.2f})")
            if h == 3 and name == "turbulent days":
                enough = n >= 40 and nd >= 20
                v = ("EDGE" if enough and T11.cp_upper(k, n) < pstar and T11.cp_upper(kd, nd) < pstar else
                     "NO EDGE" if T11.cp_lower(k, n) > pstar else "INCONCLUSIVE")
                line += f"\n  VERDICT: {v}" + ("" if enough else " (fewer than 40 trades or 20 turbulent days)")
            print(line)
    q.to_csv(os.path.join(ROOT, "research", "output", "layer11b_holdout.csv"), index=False)


if __name__ == "__main__":
    main()
