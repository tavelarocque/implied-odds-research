"""EXPLORATORY follow-up to explore_attention_vol.py: does the "Stock market crash" attention effect survive
(a) the 9-day VIX instead of the 30-day VIX, and (b) controls for recent realized volatility (yesterday's squared
return and the past 5 sessions' realized variance)? Same sample, same moving-block bootstrap. Not new comparisons:
robustness checks of the one candidate the first pass produced.
"""
import os, sys
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research"))
from config import FINAL_TEST_START
from explore_attention_vol import abnormal, block_boot

H = os.path.join(ROOT, "data", "history")


def main():
    px = pd.read_csv(os.path.join(H, "etf", "prices.csv.gz"), parse_dates=["Date"]).set_index("Date").SPY
    vix = pd.read_csv(os.path.join(H, "macro", "vix_history.csv"), parse_dates=["DATE"]).set_index("DATE").CLOSE
    v9 = pd.read_csv(os.path.join(H, "macro", "vix9d_history.csv"), parse_dates=["DATE"]).set_index("DATE").CLOSE
    wk = pd.read_csv(os.path.join(H, "attention", "wikipedia_daily.csv"), parse_dates=["date"])
    r = np.log(px).diff()
    d = pd.DataFrame({"r": r, "vix": vix, "v9": v9}).dropna()
    d["att"] = abnormal(wk[wk.article == "Stock_market_crash"].set_index("date").views).reindex(d.index)
    d = d[(d.index >= "2015-08-01") & (d.index < FINAL_TEST_START)]
    eps = 1e-8
    d["l_r2"] = np.log(d.r ** 2 + eps)
    d["l_rv5"] = np.log(sum(d.r.shift(i) ** 2 for i in range(5)) + eps)       # sessions t-4..t
    for h in (1, 5):
        rv = sum(d.r.shift(-i) ** 2 for i in range(1, h + 1))
        for label, imp, ctrl in (("30-day VIX, no controls", d.vix, False), ("9-day VIX, no controls", d.v9, False),
                                 ("9-day VIX + recent realized vol", d.v9, True)):
            s = pd.DataFrame({"y": np.log(rv + eps), "liv": np.log((imp / 100) ** 2 * h / 252), "att": d.att,
                              "l_r2": d.l_r2, "l_rv5": d.l_rv5}).dropna()
            hi = (s.att >= s.att.quantile(0.8)).astype(float).values
            cols = [np.ones(len(s)), s.liv.values] + ([s.l_r2.values, s.l_rv5.values] if ctrl else []) + [hi]
            X, y = np.column_stack(cols), s.y.values
            b = np.linalg.lstsq(X, y, rcond=None)[0][-1]
            bs = [np.linalg.lstsq(X[i], y[i], rcond=None)[0][-1] for i in block_boot(len(s))]
            lo, up = np.percentile(bs, [2.5, 97.5])
            print(f"{h}-day, {label:<32} extra realized variance after high attention {100 * (np.exp(b) - 1):+.0f}% "
                  f"(coef {b:+.3f}, {lo:+.3f} to {up:+.3f}), n {len(s)}")


if __name__ == "__main__":
    main()
