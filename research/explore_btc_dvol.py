"""EXPLORATORY: does an options-based volatility regime (Deribit's DVOL) explain layer 11's downside long-shot
overpricing better than, or on top of, crowd mood? Development sample only.

Motivation: Almeida, Grith, Miftachov & Wang (2024) find Bitcoin options price large drops relative to their realized
frequency (risk price 1.45 for -60% to -20%), most steeply when volatility is low; their two regimes are sorted mostly
by implied variance. DVOL is Deribit's 30-day implied volatility index, a direct measure of that.

Regime: DVOL at the quote time (the last completed hourly value before it), ranked against the previous 365 days of
hourly DVOL (no look-ahead): low = bottom third, high = top third. Fixed before running:
  1. Downside long-shot overpricing and selling profit by DVOL third, 1h and 3h; low minus high.
  2. Same split within fear-or-funding signal days and within other days.
  3. Profit regressed on the signal and the DVOL percentile together: does either survive the other?
Intervals: 2,000 resamples of whole settlement days. Input: research/output/explore_btc_sentiment.csv.
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rng = np.random.default_rng(81)


def day_stats(x, col):
    g = x.groupby("day")[col].agg(["sum", "count"]).values
    w = rng.multinomial(len(g), np.full(len(g), 1 / len(g)), size=2000) @ g
    return np.percentile(w[:, 0] / w[:, 1], [2.5, 97.5])


def boot_diff(x, a, b, col):
    days = x.day.unique(); idx = {d: i for i, d in enumerate(days)}
    di = x.day.map(idx).values
    sa = np.bincount(di, x[col].where(a, 0).values, len(days)); na = np.bincount(di, a.astype(float).values, len(days))
    sb = np.bincount(di, x[col].where(b, 0).values, len(days)); nb = np.bincount(di, b.astype(float).values, len(days))
    W = rng.multinomial(len(days), np.full(len(days), 1 / len(days)), size=2000)
    with np.errstate(invalid="ignore", divide="ignore"):
        d = (W @ sa) / (W @ na) - (W @ sb) / (W @ nb)
    return np.nanpercentile(d, [2.5, 97.5])


def main():
    q = pd.read_csv(os.path.join(ROOT, "research", "output", "explore_btc_sentiment.csv"))
    q = q[q.side == "down"].copy()
    q["signal"] = (q.fg <= 25) | (q.funding <= 0.0000149)
    dv = pd.read_csv(os.path.join(ROOT, "data", "history", "crypto", "dvol_btc_1h.csv"))
    dv = pd.Series(dv.close.values, index=(dv.t // 1000 + 3600).values).sort_index()     # stamped at the hour's end
    q["qt"] = pd.to_datetime(q.close, utc=True).map(lambda t: int(t.timestamp())) - q.h * 3600
    pos = np.searchsorted(dv.index.values, q.qt.values, side="right") - 1
    q["dvol"] = np.where(pos >= 0, dv.values[np.clip(pos, 0, None)], np.nan)
    hist = dv.values; idx = dv.index.values
    def pct(t, v):
        lo = np.searchsorted(idx, t - 365 * 86400); hi = np.searchsorted(idx, t, side="right")
        past = hist[lo:hi]
        return np.nan if len(past) < 24 * 180 else (past < v).mean()
    q["dvol_pct"] = [pct(t, v) for t, v in zip(q.qt.values, q.dvol.values)]
    q = q.dropna(subset=["dvol_pct"])
    q["third"] = np.where(q.dvol_pct < 1 / 3, "low", np.where(q.dvol_pct > 2 / 3, "high", "mid"))
    print(f"{len(q)} downside long-shot quotes on {q.day.nunique()} days; DVOL at the quote median {q.dvol.median():.0f} "
          f"(range {q.dvol.min():.0f} to {q.dvol.max():.0f}); days per third: "
          + ", ".join(f"{k} {v}" for k, v in q.drop_duplicates('day').third.value_counts().items()))
    print(f"Overlap: share of signal days in each third: "
          + ", ".join(f"{k} {g.drop_duplicates('day').signal.mean():.0%}" for k, g in q.groupby('third')))
    for h in (1, 3):
        x = q[q.h == h].copy()
        print(f"\n{h}h before settlement ({len(x)} quotes, {x.day.nunique()} days)")
        for t in ("low", "mid", "high"):
            s = x[x.third == t]
            lo, hi = day_stats(s, "pnl")
            print(f"  DVOL {t:<4}: n {len(s):4d} on {s.day.nunique():3d} days, overpricing {100 * s.over.mean():+.2f}c, "
                  f"paid {(s.y == 0).mean():.1%}, selling it {100 * s.pnl.mean():+.2f}c ({100 * lo:+.2f} to {100 * hi:+.2f})")
        lo, hi = boot_diff(x, x.third == "low", x.third == "high", "over")
        print(f"  overpricing, low minus high DVOL: {100 * (x[x.third == 'low'].over.mean() - x[x.third == 'high'].over.mean()):+.2f}c "
              f"({100 * lo:+.2f} to {100 * hi:+.2f})")
        for sg, name in ((True, "signal days"), (False, "other days")):
            y = x[x.signal == sg]
            a, b = y.third == "low", y.third == "high"
            if a.sum() < 10 or b.sum() < 10:
                print(f"  within {name}: too few ({a.sum()} low / {b.sum()} high)"); continue
            lo, hi = boot_diff(y, a, b, "pnl")
            print(f"  within {name}: selling it, low DVOL {100 * y[a].pnl.mean():+.2f}c vs high {100 * y[b].pnl.mean():+.2f}c; "
                  f"difference ({100 * lo:+.2f} to {100 * hi:+.2f})")
        A = np.column_stack([np.ones(len(x)), x.signal.astype(float), x.dvol_pct - 0.5]); yv = x.pnl.values
        b = np.linalg.lstsq(A, yv, rcond=None)[0]
        days = x.day.unique(); g = {d: np.where(x.day.values == d)[0] for d in days}; bs = []
        for _ in range(1000):
            ii = np.concatenate([g[d] for d in rng.choice(days, len(days))])
            bs.append(np.linalg.lstsq(A[ii], yv[ii], rcond=None)[0])
        lo, hi = np.percentile(bs, [2.5, 97.5], axis=0)
        print(f"  regression, selling profit: signal {100 * b[1]:+.2f}c ({100 * lo[1]:+.2f} to {100 * hi[1]:+.2f}); "
              f"DVOL percentile (bottom to top) {100 * b[2]:+.2f}c ({100 * lo[2]:+.2f} to {100 * hi[2]:+.2f})")


if __name__ == "__main__":
    main()
