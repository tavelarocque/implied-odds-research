"""EXPLORATORY: a single clean statement of how Kalshi's 5pm Bitcoin contracts are miscalibrated. Development sample.

Every strike in each 5pm KXBTCD set (not only long shots), quoted 1, 3 and 6 hours before settlement (last hourly
candle, spread <= 10 cents, mid). Fixed before running:
  1. Logistic recalibration, Le (2026): logit P(yes) = a + b logit(mid). b > 1: prices too close to 50% (long shots
     overpriced at both ends); a != 0: a directional bias (a > 0: YES underpriced, i.e. Bitcoin finished higher than
     priced). Fitted on all prices and on 5-95 cents (Le's range). Intervals: 1,000 resamples of whole days.
  2. Prelec probability weighting, Snowberg & Wolfers (2010): price = exp(-(-ln p)^alpha) for true probability p;
     alpha < 1 means small probabilities are overweighted. Fitted by maximum likelihood; reported with what it
     implies for a contract priced at 5 cents.
  3. CORP decomposition (Dimitriadis, Gneiting & Jordan 2021) of the Brier score: miscalibration (MCB),
     discrimination (DSC), uncertainty.
"""
import gzip, json, os, sys
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research"))
import explore_btc_sentiment as X
from explore_cpi_corp import corp, brier

rng = np.random.default_rng(91)
logit = lambda p: np.log(p / (1 - p))


def quotes():
    mk = X.load_markets()
    rows = []
    for r in mk.itertuples():
        p = os.path.join(X.KH, "candles_60m", "KXBTCD", f"{r.ticker}.json.gz")
        if not os.path.exists(p):
            continue
        cs = json.load(gzip.open(p, "rt")).get("candlesticks", [])
        if not cs:
            continue
        t = np.array([c["end_period_ts"] for c in cs])
        for h in (1, 3, 6):
            target = r.close.timestamp() - h * 3600
            i = np.searchsorted(t, target, side="right") - 1
            if i < 0 or target - t[i] > 3600:
                continue
            b, a = X.dollars(cs[i].get("yes_bid")), X.dollars(cs[i].get("yes_ask"))
            if b > 0 and a < 1 and a > b and a - b <= 0.10:
                rows.append({"day": r.close.strftime("%Y-%m-%d"), "h": h, "mid": (a + b) / 2, "y": r.y})
    return pd.DataFrame(rows)


def logit_fit(x, y, iters=50):
    A = np.column_stack([np.ones(len(x)), x]); w = np.zeros(2)
    for _ in range(iters):
        p = 1 / (1 + np.exp(-A @ w)); W = p * (1 - p) + 1e-9
        step = np.linalg.solve(A.T @ (A * W[:, None]), A.T @ (y - p)); w += step
        if np.abs(step).max() < 1e-8:
            break
    return w


def prelec_alpha(price, y):
    price = np.clip(price, 1e-4, 1 - 1e-4)
    def nll(al):
        p = np.clip(np.exp(-(-np.log(price)) ** (1 / al)), 1e-9, 1 - 1e-9)    # true prob implied by the price
        return -(y * np.log(p) + (1 - y) * np.log(1 - p)).sum()
    return minimize_scalar(nll, bounds=(0.3, 2.0), method="bounded").x


def main():
    q = quotes()
    print(f"{len(q)} quoted contract-horizons on {q.day.nunique()} days")
    for h in (1, 3, 6):
        x = q[q.h == h]
        days = x.day.unique(); g = {d: np.where(x.day.values == d)[0] for d in days}
        z, y = logit(x["mid"].clip(0.005, 0.995).values), x.y.values.astype(float)
        print(f"\n{h}h before settlement: {len(x)} contracts on {len(days)} days")
        for name, sel in (("all prices", np.ones(len(x), bool)), ("5-95 cents", (x["mid"] >= 0.05).values & (x["mid"] <= 0.95).values)):
            w = logit_fit(z[sel], y[sel]); bs = []
            for _ in range(1000):
                ii = np.concatenate([g[d] for d in rng.choice(days, len(days))]); ii = ii[sel[ii]]
                bs.append(logit_fit(z[ii], y[ii]))
            lo, hi = np.percentile(bs, [2.5, 97.5], axis=0)
            print(f"  recalibration ({name}, n {sel.sum()}): a {w[0]:+.3f} ({lo[0]:+.3f} to {hi[0]:+.3f}), "
                  f"b {w[1]:.3f} ({lo[1]:.3f} to {hi[1]:.3f})")
        al = prelec_alpha(x["mid"].values, y)
        bs = []
        for _ in range(300):
            ii = np.concatenate([g[d] for d in rng.choice(days, len(days))])
            bs.append(prelec_alpha(x["mid"].values[ii], y[ii]))
        lo, hi = np.percentile(bs, [2.5, 97.5])
        true5 = np.exp(-(-np.log(0.05)) ** (1 / al))
        print(f"  Prelec alpha {al:.3f} ({lo:.3f} to {hi:.3f}); a contract priced at 5c implies a true {100 * true5:.2f}%")
        c = corp(x["mid"].values, y, brier)
        print(f"  Brier {c[0]:.4f} = miscalibration {c[1]:.4f} - discrimination {c[2]:.4f} + uncertainty {c[3]:.4f}")


if __name__ == "__main__":
    main()
