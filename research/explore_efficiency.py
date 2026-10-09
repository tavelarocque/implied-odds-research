"""EXPLORATORY: can tomorrow's efficiency ratio be predicted, and do options already know?

Efficiency ratio of a day = |close - open| / (high - low): near 1 when the market moved one way and held it, near 0
when it chopped back and forth. SPY daily bars from 1993 (SPY's opens are real trades; Yahoo's ^GSPC opens before 2006
are just the previous close). Development sample only: everything from FINAL_TEST_START on is dropped.

Model: logistic regression on 15 features known at today's close, predicting whether tomorrow's efficiency is above
the median of the training years. Walk-forward: train on every year before Y, test on year Y, Y = 1997 .. 2026 (Q1).
Features are standardized with the training years' means and SDs; light L2 penalty.

Two checks, fixed here before any result:
  1. Out-of-sample AUC of the model vs two simple baselines: today's efficiency, and its 20-day mean.
     Interval for the difference: 1,000 resamples of 20-day blocks of test days.
  2. The one that matters for trading options or Kalshi: on days the model calls choppy (bottom fifth of predicted
     probability), is tomorrow's net move smaller than the VIX said it would be? Net move = |close-to-close return|
     (Kalshi's daily index contracts settle on the close), divided by the VIX's one-day standard deviation
     (VIX / 100 / sqrt(252)); VIX9D from 2011 as well. Compared with the other four fifths, same block resampling.
     Also: open-to-close |move| (what the efficiency ratio's numerator measures), and the day's range.
"""
import os, sys
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import rankdata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research"))
from config import FINAL_TEST_START
rng = np.random.default_rng(21)
CHOP = 0.3


def vix(name):
    v = pd.read_csv(os.path.join(ROOT, "data", "history", "macro", f"{name}_history.csv"))
    return pd.Series(v.CLOSE.values, index=pd.to_datetime(v.DATE, format="%m/%d/%Y"))


def features(d):
    eff = (d.Close - d.Open).abs() / (d.High - d.Low)
    r = np.log(d.Close).diff()
    rv20 = r.rolling(20).std()
    chop = (eff < CHOP).astype(float)
    streak = chop.groupby((chop == 0).cumsum()).cumsum()
    hi20, lo20 = d.High.rolling(20).max().shift(), d.Low.rolling(20).min().shift()
    fake = (((d.High > hi20) & (d.Close < hi20)) | ((d.Low < lo20) & (d.Close > lo20))).astype(float)
    r5 = np.log(d.Close).diff(5)
    rng_ = (d.High - d.Low) / d.Close
    X = pd.DataFrame({
        "rv20": np.log(rv20 * np.sqrt(252)),
        "eff": eff,
        "eff_lag1": eff.shift(1),
        "eff_lag2": eff.shift(2),
        "eff5": eff.rolling(5).mean(),
        "eff10": eff.rolling(10).mean(),
        "eff20": eff.rolling(20).mean(),
        "var_ratio": np.log(r5.rolling(60).var() / (5 * r.rolling(60).var())),
        "fake_breakouts20": fake.rolling(20).mean(),
        "dist_ma50": (d.Close / d.Close.rolling(50).mean() - 1) / rv20,
        "chop_streak": np.log1p(streak),
        "vol_change": np.log(r.rolling(5).std() / rv20),
        "chop5": chop.rolling(5).mean(),
        "chop10": chop.rolling(10).mean(),
        "range_vs_20d": np.log(rng_ / rng_.rolling(20).mean()),
    })
    return X, eff


def fit_logit(X, y, lam=1.0):
    Xb = np.column_stack([np.ones(len(X)), X])
    def f(w):
        z = Xb @ w
        ll = np.sum(np.logaddexp(0, z) - y * z) + lam * np.sum(w[1:] ** 2) / 2
        g = Xb.T @ (1 / (1 + np.exp(-z)) - y); g[1:] += lam * w[1:]
        return ll, g
    return minimize(f, np.zeros(Xb.shape[1]), jac=True, method="L-BFGS-B").x


def auc(s, y):
    rk = rankdata(s); n1 = y.sum(); n0 = len(y) - n1
    return (rk[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)


def blocks(n, size=20):
    starts = np.arange(0, n, size)
    pick = rng.choice(starts, size=len(starts))
    return np.concatenate([np.arange(s, min(s + size, n)) for s in pick])


def main():
    d = pd.read_csv(os.path.join(ROOT, "data", "history", "index", "spy_daily.csv"), index_col=0, parse_dates=True)
    d = d[d.index < FINAL_TEST_START]
    X, eff = features(d)
    D = X.copy()
    D["y_eff"] = eff.shift(-1)
    D["move_cc"] = np.log(d.Close).diff().shift(-1).abs()
    D["move_oc"] = np.log(d.Close / d.Open).shift(-1).abs()
    D["range"] = np.log(d.High / d.Low).shift(-1)
    D["vix_sd"] = vix("vix").reindex(D.index) / 100 / np.sqrt(252)
    D["vix9_sd"] = vix("vix9d").reindex(D.index) / 100 / np.sqrt(252)
    D = D.dropna(subset=list(X.columns) + ["y_eff"])
    cols = list(X.columns)

    preds = []
    for Y in range(1997, 2027):
        tr, te = D[D.index.year < Y], D[D.index.year == Y]
        if te.empty:
            continue
        mu, sd = tr[cols].mean(), tr[cols].std()
        med = tr.y_eff.median()
        w = fit_logit(((tr[cols] - mu) / sd).values, (tr.y_eff > med).astype(float).values)
        z = w[0] + ((te[cols] - mu) / sd).values @ w[1:]
        z_tr = w[0] + ((tr[cols] - mu) / sd).values @ w[1:]
        p = te.copy(); p["prob"] = 1 / (1 + np.exp(-z)); p["clean"] = (te.y_eff > med).astype(int)
        p["chopq"] = z <= np.quantile(z_tr, 0.2)          # cut-off from the training years, not the test year
        preds.append(p)
    P = pd.concat(preds)
    last_w = pd.Series(w[1:], index=cols).sort_values()
    print(f"SPY {d.index[0].date()} to {d.index[-1].date()}; out-of-sample test days {len(P)} "
          f"({P.index[0].year} to {P.index[-1].date()}); median efficiency {D.y_eff.median():.2f}")
    print("Weights of the last fit (standardized features): " + ", ".join(f"{k} {v:+.2f}" for k, v in last_w.items()))

    y = P.clean.values
    scores = {"model": P.prob.values, "today's efficiency": P.eff.values, "20-day mean efficiency": P.eff20.values}
    print("\n1. Out-of-sample AUC for 'tomorrow is a clean day' (0.50 = coin flip):")
    base = {k: auc(v, y) for k, v in scores.items()}
    for k, v in base.items():
        print(f"   {k:<24} {v:.3f}")
    diffs = {k: [] for k in scores if k != "model"}
    for _ in range(1000):
        i = blocks(len(P))
        a = auc(scores["model"][i], y[i])
        for k in diffs:
            diffs[k].append(a - auc(scores[k][i], y[i]))
    for k, v in diffs.items():
        lo, hi = np.percentile(v, [2.5, 97.5])
        print(f"   model minus {k}: {base['model'] - base[k]:+.3f} ({lo:+.3f} to {hi:+.3f})")
    by_era = P.groupby((P.index.year - 1) // 10 * 10 + 1).apply(lambda g: auc(g.prob.values, g.clean.values))
    print("   model AUC by decade: " + ", ".join(f"{k}s {v:.3f}" for k, v in by_era.items()))

    print("\n2. Tomorrow's move vs what the VIX implied, model's choppiest fifth vs the rest:")
    print(f"   (model's choppy fifth, cut-off set on training years: {P.chopq.mean():.0%} of test days)")
    for vcol, start in (("vix_sd", None), ("vix9_sd", "2011-01-04")):
        S = P.dropna(subset=[vcol])
        if start:
            S = S[S.index >= start]
        for mcol, label in (("move_cc", "close-to-close |move|"), ("move_oc", "open-to-close |move|"), ("range", "high-low range")):
            ratio = (S[mcol] / S[vcol]).values; q = S.chopq.values.astype(bool)
            a, b = ratio[q].mean(), ratio[~q].mean()
            bs = []
            for _ in range(1000):
                i = blocks(len(S)); qi = q[i]
                bs.append(ratio[i][qi].mean() / ratio[i][~qi].mean() - 1)
            lo, hi = np.percentile(bs, [2.5, 97.5])
            print(f"   {vcol[:-3].upper():<5} {label:<22} choppy fifth {a:.3f}x implied, rest {b:.3f}x; "
                  f"difference {100 * (a / b - 1):+.0f}% ({100 * lo:+.0f}% to {100 * hi:+.0f}%)  [{len(S)} days]")
        # does the prediction add anything once the VIX's own forecast and recent realized vol are known?
        S2 = S.assign(lr=np.log(S.move_cc + 1e-5) - np.log(S[vcol]), lrv=np.log(np.exp(S.rv20) / np.sqrt(252)) - np.log(S[vcol]))
        A = np.column_stack([np.ones(len(S2)), S2.lrv, S2.prob - 0.5])
        b_, *_ = np.linalg.lstsq(A, S2.lr.values, rcond=None)
        bs = []
        for _ in range(500):
            i = blocks(len(S2)); bs.append(np.linalg.lstsq(A[i], S2.lr.values[i], rcond=None)[0][2])
        lo, hi = np.percentile(bs, [2.5, 97.5])
        print(f"   {vcol[:-3].upper():<5} log(|move|/implied) on predicted P(clean), controlling for 20-day realized/implied: "
              f"{b_[2]:+.2f} per unit of probability ({lo:+.2f} to {hi:+.2f})")
    P.to_csv(os.path.join(ROOT, "research", "output", "explore_efficiency.csv.gz"))


if __name__ == "__main__":
    main()
