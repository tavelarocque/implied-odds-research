"""EXPLORATORY: does public attention predict S&P 500 volatility beyond what the VIX already prices?

Data before FINAL_TEST_START only, kept to the project's development period. Looks for a hypothesis, tests nothing.

On each trading day t, at the close: the VIX (the options market's 30-day volatility forecast) and attention, the
log of day t's Wikipedia views over the median of the 28 days before (a UTC day ends at 8pm ET, so it is known before
the next session opens). Target: realized variance over the next 1 and 5 sessions, from SPY closes.
Regression: log(realized variance) on log(VIX-implied variance for the same horizon) and an attention dummy (top fifth).
If attention matters beyond the VIX, the dummy's coefficient is positive: options under-price the moves that follow
attention spikes. Also reported: the variance risk premium (implied minus realized variance) on high-attention days
vs other days, which is what a seller of options would earn.
Four comparisons, fixed here: {S&P 500 page, Stock market crash page} x {1 day, 5 days}.
Intervals: moving-block bootstrap (blocks of 20 sessions, 2,000 draws), because volatility clusters.

Run from the project root, after collect/attention_history.py and saving Cboe's VIX_History.csv to
data/history/macro/vix_history.csv.
"""
import os, sys
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research"))
from config import FINAL_TEST_START
rng = np.random.default_rng(12)


def abnormal(v):
    v = v.sort_index().asfreq("D")
    return np.log(v / v.shift(1).rolling(28, min_periods=20).median())


def block_boot(n, block=20, draws=2000):
    starts = rng.integers(0, n - block, size=(draws, int(np.ceil(n / block))))
    return [np.concatenate([np.arange(s, s + block) for s in row])[:n] for row in starts]


def main():
    px = pd.read_csv(os.path.join(ROOT, "data", "history", "etf", "prices.csv.gz"), parse_dates=["Date"]).set_index("Date").SPY
    vix = pd.read_csv(os.path.join(ROOT, "data", "history", "macro", "vix_history.csv"), parse_dates=["DATE"]).set_index("DATE").CLOSE
    wk = pd.read_csv(os.path.join(ROOT, "data", "history", "attention", "wikipedia_daily.csv"), parse_dates=["date"])
    r = np.log(px).diff()
    d = pd.DataFrame({"r": r, "vix": vix}).dropna()
    for a in ("S&P_500", "Stock_market_crash"):
        d[a] = abnormal(wk[wk.article == a].set_index("date").views).reindex(d.index)
    d = d[(d.index >= "2015-08-01") & (d.index < FINAL_TEST_START)]
    print(f"{len(d)} sessions, {d.index.min():%Y-%m-%d} to {d.index.max():%Y-%m-%d}")
    for h in (1, 5):
        rv = sum(d.r.shift(-i) ** 2 for i in range(1, h + 1))
        iv = (d.vix / 100) ** 2 * h / 252
        for a in ("S&P_500", "Stock_market_crash"):
            s = pd.DataFrame({"lrv": np.log(rv), "liv": np.log(iv), "att": d[a], "vrp": iv - rv}).dropna()
            s = s[np.isfinite(s.lrv)]
            hi = (s.att >= s.att.quantile(0.8)).astype(float).values
            X = np.column_stack([np.ones(len(s)), s.liv.values, hi])
            y = s.lrv.values
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
            bs = []
            for idx in block_boot(len(s)):
                bs.append(np.linalg.lstsq(X[idx], y[idx], rcond=None)[0][2])
            lo, up = np.percentile(bs, [2.5, 97.5])
            vh, vo = s.vrp[hi == 1].mean(), s.vrp[hi == 0].mean()
            dv = [s.vrp.values[idx][hi[idx] == 1].mean() - s.vrp.values[idx][hi[idx] == 0].mean() for idx in block_boot(len(s))]
            dlo, dup = np.percentile(dv, [2.5, 97.5])
            print(f"\n{h}-day horizon, attention = {a} (top fifth = {int(hi.sum())} sessions):")
            print(f"  realized variance after high attention is {100 * (np.exp(beta[2]) - 1):+.0f}% vs what the VIX implies "
                  f"for other days (coefficient {beta[2]:+.3f}, {lo:+.3f} to {up:+.3f}); VIX loading {beta[1]:.2f}")
            print(f"  variance risk premium (implied minus realized, annualized vol points^2 x 1e4): high attention "
                  f"{1e4 * vh * 252 / h:+.1f} vs other {1e4 * vo * 252 / h:+.1f}; difference "
                  f"{1e4 * (vh - vo) * 252 / h:+.1f} ({1e4 * dlo * 252 / h:+.1f} to {1e4 * dup * 252 / h:+.1f})")


if __name__ == "__main__":
    main()
