"""EXPLORATORY, layer 10 revisited with better scoring tools (papers read 2026-10-09):

1. CORP decomposition (Dimitriadis, Gneiting & Jordan 2021): score = MCB - DSC + UNC, where MCB (miscalibration) is
   how much the forecast loses to its own isotonic (PAV) recalibration and DSC (discrimination) how much the
   recalibrated forecast beats the base rate. Both forecasts face the same outcomes, so UNC is shared and
   the Brier gap = gap in MCB - gap in DSC: is Kalshi better because the nowcast is miscalibrated, or because Kalshi
   carries more information? Brier and log score. Intervals: 2,000 resamples of whole CPI releases.
2. Diebold-Mariano (Diebold 2015): per-release mean loss difference, Newey-West variance (2 lags), and the
   conditional version: does the gap grow with |Kalshi - nowcast|?
Input: research/output/explore_cpi.csv (layer 10's contract rows: Kalshi mid, nowcast probability p_now, outcome y).
"""
import os
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rng = np.random.default_rng(71)


def pav(y, w):
    v, ww, n = [], [], []
    for yi, wi in zip(y, w):
        v.append(yi); ww.append(wi); n.append(1)
        while len(v) > 1 and v[-2] > v[-1]:
            tw = ww[-2] + ww[-1]; tv = (v[-2] * ww[-2] + v[-1] * ww[-1]) / tw; tn = n[-2] + n[-1]
            v[-2:], ww[-2:], n[-2:] = [tv], [tw], [tn]
    return np.repeat(v, n)


def recal(x, y):
    u, inv = np.unique(x, return_inverse=True)
    w = np.bincount(inv).astype(float); m = np.bincount(inv, y) / w
    return pav(m, w)[inv]


def brier(p, y): return (p - y) ** 2
def logs(p, y):
    p = np.clip(p, 0.005, 0.995); return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def corp(x, y, S):
    xc = recal(x, y); r = np.full_like(x, y.mean())
    sx, sc, sr = S(x, y).mean(), S(xc, y).mean(), S(r, y).mean()
    return np.array([sx, sx - sc, sr - sc, sr])      # score, MCB, DSC, UNC


def nw_t(d, L=2):
    T = len(d); e = d - d.mean(); g = e @ e / T
    for l in range(1, L + 1):
        g += 2 * (1 - l / (L + 1)) * (e[l:] @ e[:-l]) / T
    return d.mean() / np.sqrt(g / T)


def main():
    q = pd.read_csv(os.path.join(ROOT, "research", "output", "explore_cpi.csv"))
    q = q.dropna(subset=["mid", "p_now", "y"])
    for series, s in [("all", q)] + list(q.groupby("series")):
        x, n, y = s["mid"].values, s["p_now"].values, s["y"].values.astype(float)
        print(f"\n{series}: {len(s)} contracts in {s.event.nunique()} releases (base rate {y.mean():.2f})")
        for name, S in (("Brier", brier), ("log score", logs)):
            k, c = corp(x, y, S), corp(n, y, S)
            ev = s.event.values; uev = np.unique(ev); idx = {e: np.where(ev == e)[0] for e in uev}
            bs = []
            for _ in range(2000):
                ii = np.concatenate([idx[e] for e in rng.choice(uev, len(uev))])
                bs.append(corp(x[ii], y[ii], S) - corp(n[ii], y[ii], S))
            lo, hi = np.percentile(bs, [2.5, 97.5], axis=0)
            print(f"  {name:<9}  Kalshi: score {k[0]:.4f} = MCB {k[1]:.4f} - DSC {k[2]:.4f} + UNC {k[3]:.4f}")
            print(f"  {'':<9}  nowcast: score {c[0]:.4f} = MCB {c[1]:.4f} - DSC {c[2]:.4f} + UNC {c[3]:.4f}")
            d = k - c
            print(f"  {'':<9}  Kalshi minus nowcast: score {d[0]:+.4f} ({lo[0]:+.4f} to {hi[0]:+.4f}); "
                  f"MCB {d[1]:+.4f} ({lo[1]:+.4f} to {hi[1]:+.4f}); DSC {d[2]:+.4f} ({lo[2]:+.4f} to {hi[2]:+.4f})")
        # Diebold-Mariano on per-release mean Brier differences, in release order
        s2 = s.assign(d=brier(x, y) - brier(n, y), gap=np.abs(x - n)).sort_values("date")
        per = s2.groupby("event", sort=False).agg(d=("d", "mean"), gap=("gap", "mean"), date=("date", "first")).sort_values("date")
        t = nw_t(per.d.values)
        A = np.column_stack([np.ones(len(per)), per.gap.values]); b = np.linalg.lstsq(A, per.d.values, rcond=None)[0]
        print(f"  Diebold-Mariano (Brier, per release, Newey-West): mean {per.d.mean():+.4f}, t = {t:.2f} "
              f"({len(per)} releases); conditional: loss gap = {b[0]:+.4f} {b[1]:+.4f} x mean|Kalshi - nowcast|")


if __name__ == "__main__":
    main()
