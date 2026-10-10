"""EXPLORATORY: does the shape of Kalshi's implied Bitcoin distribution tilt with crowd mood?

Lee, Lee and Lee (SSRN 6748186) find Kalshi's risk-neutral Bitcoin distributions symmetric on average (Oct 2025 to
Feb 2026). Layer 11 finds the downside long shot more overpriced on fear days. Both can hold if the distribution tilts
to the downside on fear days and the other way on other days. This checks that, on layer 11's development sample only
(5pm ET KXBTCD sets settling before FINAL_TEST_START), 1, 3 and 6 hours before settlement.

Per set and horizon: every strike's yes mid from the last hourly candle (spread <= 10 cents), a monotone fit across
strikes (pool-adjacent-violators), giving the market's probability that Bitcoin finishes below each strike. From it,
by linear interpolation in log strike: the 10th, 50th and 90th percentiles, and Bowley's quantile skewness
(q90 + q10 - 2 q50) / (q90 - q10): negative = the downside tail is priced longer than the upside. Scale-free, so days
with different volatility compare. Only sets whose quoted strikes reach both the 10% and 90% points. (The strike
list was downloaded for strikes within 4% of the settled price; the percentiles use only the quotes at the time.)

Fixed before running: skewness on fear days (F&G <= 25), funding bottom-fifth days, and either (layer 11's signal) vs
other days; correlation with the Fear & Greed level; and whether a set's skewness relates to that day's profit from
selling its downside long shots. Intervals: 2,000 resamples of 10-day blocks (skewness is persistent day to day).
"""
import gzip, json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research"))
import explore_btc_sentiment as X

rng = np.random.default_rng(51)
FG_MAX, FUND_MAX = 25, 0.0000149


def pav(y):
    """Pool-adjacent-violators: non-decreasing fit."""
    v, w = list(map(float, y)), [1.0] * len(y)
    i = 0
    while i < len(v) - 1:
        if v[i] > v[i + 1]:
            nv = (v[i] * w[i] + v[i + 1] * w[i + 1]) / (w[i] + w[i + 1])
            v[i:i + 2], w[i:i + 2] = [nv], [w[i] + w[i + 1]]
            i = max(i - 1, 0)
        else:
            i += 1
    return np.repeat(v, np.array(w, int))


def quantile(lk, cdf, p):
    j = np.searchsorted(cdf, p)
    if j == 0 or j >= len(cdf) or cdf[j] == cdf[j - 1]:
        return np.nan
    return lk[j - 1] + (p - cdf[j - 1]) / (cdf[j] - cdf[j - 1]) * (lk[j] - lk[j - 1])


def shapes():
    mk = X.load_markets()
    rows = []
    for ev, em in mk.groupby("event"):
        close = em.close.iloc[0]
        per_h = {1: [], 3: [], 6: []}
        for r in em.itertuples():
            p = os.path.join(X.KH, "candles_60m", "KXBTCD", f"{r.ticker}.json.gz")
            if not os.path.exists(p):
                continue
            cs = json.load(gzip.open(p, "rt")).get("candlesticks", [])
            if not cs:
                continue
            t = np.array([c["end_period_ts"] for c in cs])
            for h in per_h:
                i = np.searchsorted(t, close.timestamp() - h * 3600, side="right") - 1
                if i < 0 or close.timestamp() - h * 3600 - t[i] > 3600:
                    continue
                b, a = X.dollars(cs[i].get("yes_bid")), X.dollars(cs[i].get("yes_ask"))
                if b > 0 and a < 1 and a > b and a - b <= 0.10:
                    per_h[h].append((r.k, 1 - (a + b) / 2))
        for h, pts in per_h.items():
            if len(pts) < 5:
                continue
            pts.sort()
            lk = np.log([k for k, _ in pts]); cdf = pav([c for _, c in pts])
            q10, q50, q90 = (quantile(lk, cdf, p) for p in (0.10, 0.50, 0.90))
            if not np.isfinite([q10, q50, q90]).all() or q90 <= q10:
                continue
            rows.append({"day": close.strftime("%Y-%m-%d"), "close": close, "h": h, "n_strikes": len(pts),
                         "bskew": (q90 + q10 - 2 * q50) / (q90 - q10), "width": q90 - q10,
                         "down": q50 - q10, "up": q90 - q50})
    return pd.DataFrame(rows)


def block_boot(vals_fn, n_days, n=2000, size=10):
    starts = np.arange(0, n_days, size)
    out = []
    for _ in range(n):
        pick = rng.choice(starts, size=len(starts))
        out.append(vals_fn(np.concatenate([np.arange(s, min(s + size, n_days)) for s in pick])))
    return np.nanpercentile(out, [2.5, 97.5])


def main():
    s = shapes()
    m = X.mood(s.groupby("day").close.first())
    s = s.join(m, on="day")
    s["fear"] = s.fg <= FG_MAX; s["lowfund"] = s.funding <= FUND_MAX; s["signal"] = s.fear | s.lowfund
    q = pd.read_csv(os.path.join(ROOT, "research", "output", "explore_btc_sentiment.csv"))
    pnl = q[q.side == "down"].groupby(["day", "h"]).pnl.mean().rename("ls_pnl")
    s = s.join(pnl, on=["day", "h"])
    print(f"Kalshi 5pm BTC sets, development sample: {s.day.nunique()} days with a measurable shape "
          f"(median {s.n_strikes.median():.0f} quoted strikes)")
    for h in (1, 3, 6):
        x = s[s.h == h].sort_values("day").reset_index(drop=True)
        n = len(x)
        lo, hi = block_boot(lambda i: x.bskew.values[i].mean(), n)
        print(f"\n{h}h before settlement, {n} days: mean Bowley skewness {x.bskew.mean():+.3f} ({lo:+.3f} to {hi:+.3f}); "
              f"median {x.bskew.median():+.3f}; downside half-width {100 * x.down.mean():.2f}% vs upside {100 * x.up.mean():.2f}%")
        for flag, name in (("fear", "fear (F&G <= 25)"), ("lowfund", "funding bottom fifth"), ("signal", "fear or funding")):
            f = x[flag].fillna(False).values.astype(bool)
            if f.sum() < 10:
                print(f"   {name}: too few days ({f.sum()})"); continue
            d = x.bskew.values[f].mean() - x.bskew.values[~f].mean()
            lo, hi = block_boot(lambda i: x.bskew.values[i][f[i]].mean() - x.bskew.values[i][~f[i]].mean(), n)
            print(f"   {name:<22} {x.bskew.values[f].mean():+.3f} ({f.sum()} days) vs other days {x.bskew.values[~f].mean():+.3f}; "
                  f"difference {d:+.3f} ({lo:+.3f} to {hi:+.3f})")
        ok = x.fg.notna()
        c = np.corrcoef(x.fg[ok], x.bskew[ok])[0, 1]
        idx = np.where(ok)[0]
        lo, hi = block_boot(lambda i: np.corrcoef(x.fg.values[idx][i % len(idx)], x.bskew.values[idx][i % len(idx)])[0, 1], len(idx))
        print(f"   correlation of skewness with the Fear & Greed level: {c:+.2f} ({lo:+.2f} to {hi:+.2f})")
        y = x.dropna(subset=["ls_pnl"])
        if len(y) > 30:
            c2 = np.corrcoef(y.bskew, y.ls_pnl)[0, 1]
            lo2 = y.bskew.quantile(1 / 3)
            print(f"   days with downside long shots ({len(y)}): correlation of skewness with selling them {c2:+.2f}; "
                  f"mean profit on the most left-skewed third {100 * y[y.bskew <= lo2].ls_pnl.mean():+.2f}c vs rest "
                  f"{100 * y[y.bskew > lo2].ls_pnl.mean():+.2f}c")
    s.to_csv(os.path.join(ROOT, "research", "output", "explore_skew.csv"), index=False)


if __name__ == "__main__":
    main()
