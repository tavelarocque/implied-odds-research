"""Layer 13c (research/PREREGISTRATION_LAYER13C.md): fit the meta-labeling filter on layer 13's development-window
trades, 3 hours out, and freeze it in research/layer13c_model.json. Development data only.

    python3 research/fit_layer13c.py
"""
import gzip, json, math, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research"))
import test_layer13_lognormal as T

H, START, END = 3, "2025-09-01", "2026-03-31"
FEATURES = ["dist_sd", "spread", "er24", "dvol"]
OUT = os.path.join(ROOT, "research", "layer13c_model.json")


def dev_trades():
    cb = pd.read_csv(os.path.join(ROOT, "data", "history", "crypto", "coinbase_1h.csv")).sort_values("t")
    cb = cb.drop_duplicates("t").set_index("t")
    dv = pd.read_csv(os.path.join(ROOT, "data", "history", "crypto", "dvol_btc_1h.csv"))
    dv = pd.Series(dv.close.values, index=(dv.t // 1000 + 3600).values).sort_index()       # stamped at the hour's end
    rows = []
    bc, cc = T.COEF[H]
    for r in T.markets(START, END).itertuples():
        qt = r.end - H * 3600
        x = cb[cb.index + 3600 <= qt].iloc[-24:]
        if len(x) < 24 or x.index[-1] + 3600 != qt:
            continue
        S = float(x.close.iloc[-1])
        if abs(r.k / S - 1) > T.BAND:
            continue
        p = os.path.join(T.KH, "candles_60m", "KXBTCD", f"{r.ticker}.json.gz")
        if not os.path.exists(p):
            continue
        cs = json.load(gzip.open(p, "rt")).get("candlesticks", [])
        t = np.array([c["end_period_ts"] for c in cs])
        i = np.searchsorted(t, qt, side="right") - 1 if len(cs) else -1
        if i < 0 or qt - t[i] > 3600:
            continue
        b, a = T.dollars(cs[i].get("yes_bid")), T.dollars(cs[i].get("yes_ask"))
        if not (b > 0 and a < 1 and a > b and a - b <= 0.10):
            continue
        sigma = np.diff(np.log(x.close.values)).std(ddof=1)
        vol = sigma * math.sqrt(H)
        ln = 0.5 * (1 + math.erf(math.log(S / r.k) / (vol * math.sqrt(2))))
        mid = (a + b) / 2
        blend = 1 / (1 + math.exp(-(bc * T.logit(mid) + cc * T.logit(ln))))
        if blend - a - T.fee(a) > T.MARGIN:
            pnl = r.y - a - T.fee(a)
        elif b - blend - T.fee(b) > T.MARGIN:
            pnl = b - r.y - T.fee(b)
        else:
            continue
        j = np.searchsorted(dv.index.values, qt, side="right") - 1
        rows.append({"day": r.day, "k": r.k, "pnl": pnl, "win": float(pnl > 0),
                     "dist_sd": abs(math.log(S / r.k)) / vol, "spread": a - b,
                     "er24": abs(x.close.iloc[-1] - x.open.iloc[0]) / (x.high.max() - x.low.min()),
                     "dvol": float(dv.values[j]) if j >= 0 and qt - dv.index.values[j] <= 3600 else np.nan})
    return pd.DataFrame(rows)


def fit(X, y, iters=100):
    A = np.column_stack([np.ones(len(X)), X]); w = np.zeros(A.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-A @ w)); W = p * (1 - p) + 1e-9
        step = np.linalg.solve(A.T @ (A * W[:, None]), A.T @ (y - p)); w += step
        if np.abs(step).max() < 1e-10:
            break
    return w


def prob(w, mu, sd, X):
    Z = (X - mu) / sd
    return 1 / (1 + np.exp(-(w[0] + Z @ w[1:])))


def main():
    d = dev_trades().dropna(subset=FEATURES).reset_index(drop=True)
    X, y = d[FEATURES].values, d.win.values
    mu, sd = X.mean(0), X.std(0, ddof=0)
    w = fit((X - mu) / sd, y)
    d["p"] = prob(w, mu, sd, X)
    print(f"{len(d)} development trades on {d.day.nunique()} days, win rate {y.mean():.1%}, mean {100 * d.pnl.mean():+.2f}c")
    print("coefficients (standardized): intercept {:+.3f}, ".format(w[0]) +
          ", ".join(f"{f} {c:+.3f}" for f, c in zip(FEATURES, w[1:])))
    tk = d.p > 0.5
    print(f"in sample: takes {tk.mean():.0%}; taken {100 * d.pnl[tk].mean():+.2f}c vs rejected {100 * d.pnl[~tk].mean():+.2f}c")
    # leave one month out: the honest in-development check of whether the filter generalizes at all
    m = d.day.str[:7]; out = np.zeros(len(d))
    for mo in m.unique():
        tr = (m != mo).values
        mu2, sd2 = X[tr].mean(0), X[tr].std(0, ddof=0)
        out[~tr] = prob(fit((X[tr] - mu2) / sd2, y[tr]), mu2, sd2, X[~tr])
    tk2 = out > 0.5
    print(f"leave one month out: takes {tk2.mean():.0%}; taken {100 * d.pnl[tk2].mean():+.2f}c "
          f"({tk2.sum()} trades) vs rejected {100 * d.pnl[~tk2].mean():+.2f}c ({(~tk2).sum()} trades)")
    json.dump({"features": FEATURES, "mean": mu.tolist(), "sd": sd.tolist(), "coef": w.tolist(), "threshold": 0.5,
               "trained_on": f"layer 13 development trades {START} to {END}, {H}h, n={len(d)}"},
              open(OUT, "w"), indent=1)
    print(f"frozen -> {os.path.relpath(OUT, ROOT)}")


if __name__ == "__main__":
    main()
