"""EXPLORATORY: hidden Markov regimes. Do they tell us anything the VIX, the trend or crypto mood do not?

A Gaussian hidden Markov model with K unseen states, fitted on each day's (log return, log high/low range), both
standardized on the training years. States are labelled by their typical range, calmest first, so refits cannot swap
the labels. Only FILTERED probabilities are used: the state probability at day t's close from data up to t, pushed one
day ahead through the transition matrix. (Smoothed probabilities use the future and make regimes look perfect.)
Walk-forward: refit on every year before Y, filter year Y. K = 2 is the primary model, K = 3 is reported.
Development data only (before FINAL_TEST_START).

Part A, S&P (SPY daily bars, test 1997 to 2026-03). Same question as research/explore_efficiency.py: tomorrow's
|close-to-close move| divided by the VIX's one-day move, regressed on the turbulent-state probability with controls for
20-day realized vs implied volatility, the VIX level and distance from the 50-day average; 20-day block bootstrap.
Part B, Bitcoin (Yahoo BTC-USD daily bars from 2014-09). For layer 11's development sample of Kalshi long shots
(research/output/explore_btc_sentiment.csv): is the downside long shot more overpriced when the model says turbulent
(K = 2) or bearish (K = 3, the state with the lowest mean return), and does that add to the fear-or-funding signal?
Day bootstrap, as in layer 11.
"""
import os, sys
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research"))
from config import FINAL_TEST_START
rng = np.random.default_rng(31)


# ---------------------------------------------------------------- the model
def emissions(X, mu, var):
    lb = -0.5 * (((X[:, None, :] - mu[None]) ** 2) / var[None] + np.log(2 * np.pi * var[None])).sum(2)
    m = lb.max(1, keepdims=True)
    return np.exp(lb - m), m[:, 0]


def forward(B, pi, A):
    T, K = B.shape
    al, c = np.empty((T, K)), np.empty(T)
    a = pi * B[0]
    for t in range(T):
        if t:
            a = (a @ A) * B[t]
        c[t] = a.sum(); a = a / c[t]; al[t] = a
    return al, c


def em(X, p, iters=80, tol=1e-5):
    pi, A, mu, var = p
    last = -np.inf
    for _ in range(iters):
        B, m = emissions(X, mu, var)
        al, c = forward(B, pi, A)
        T, K = B.shape
        be = np.ones((T, K))
        for t in range(T - 2, -1, -1):
            be[t] = (A @ (B[t + 1] * be[t + 1])) / c[t + 1]
        g = al * be; g /= g.sum(1, keepdims=True)
        xi = A * (al[:-1].T @ (B[1:] * be[1:] / c[1:, None]))
        pi, A = g[0], xi / xi.sum(1, keepdims=True)
        n = g.sum(0)
        mu = (g.T @ X) / n[:, None]
        var = np.maximum((g.T @ X ** 2) / n[:, None] - mu ** 2, 1e-3)
        ll = np.log(c).sum() + m.sum()
        if ll - last < tol * abs(ll):
            break
        last = ll
    return (pi, A, mu, var), ll


def init(X, K, jitter):
    q = np.argsort(np.argsort(X[:, 1])) * K // len(X)                # states by range rank
    mu = np.array([X[q == k].mean(0) for k in range(K)]) + jitter * rng.normal(size=(K, X.shape[1]))
    var = np.array([X[q == k].var(0) for k in range(K)]) + 1e-2
    A = np.full((K, K), 0.05 / (K - 1)); np.fill_diagonal(A, 0.95)
    return np.full(K, 1 / K), A, mu, var


def fit(X, K, warm=None):
    starts = [init(X, K, 0.0), init(X, K, 0.3)] + ([warm] if warm is not None else [])
    best = max((em(X, s) for s in starts), key=lambda r: r[1])[0]
    o = np.argsort(best[2][:, 1])                                    # calmest state first
    pi, A, mu, var = best
    return pi[o], A[np.ix_(o, o)], mu[o], var[o]


def walk_forward(d, K, first_test_year):
    """d: daily OHLC. Returns a frame of next-day state probabilities, each from a model fitted on earlier years."""
    obs = pd.DataFrame({"r": np.log(d.Close).diff(), "rg": np.log(np.log(d.High / d.Low).clip(lower=1e-5))}).dropna()
    out, warm = [], None
    for Y in range(first_test_year, obs.index.max().year + 1):
        tr = obs[obs.index.year < Y]
        mu_, sd_ = tr.mean(), tr.std()
        p = fit(((tr - mu_) / sd_).values, K, warm)
        warm = p
        upto = obs[obs.index.year <= Y]                               # filter from the start, keep year Y
        B, _ = emissions(((upto - mu_) / sd_).values, p[2], p[3])
        al, _ = forward(B, p[0], p[1])
        nxt = al @ p[1]
        f = pd.DataFrame(nxt, index=upto.index, columns=[f"s{k}" for k in range(K)])
        f["bear"] = nxt[:, int(np.argmin(p[2][:, 0]))]               # state with the lowest mean return
        out.append(f[f.index.year == Y])
    return pd.concat(out), p


def blocks(n, size=20):
    s = np.arange(0, n, size); pick = rng.choice(s, size=len(s))
    return np.concatenate([np.arange(a, min(a + size, n)) for a in pick])


def describe(p, K, sd_r):
    pi, A, mu, var = p
    return "; ".join(f"state {k}: stays {A[k, k]:.2f}/day (~{1 / (1 - A[k, k]):.0f} days), "
                     f"mean return {mu[k, 0]:+.2f} sd, range {mu[k, 1]:+.2f} sd" for k in range(K))


# ---------------------------------------------------------------- part A, S&P
def vix(name):
    v = pd.read_csv(os.path.join(ROOT, "data", "history", "macro", f"{name}_history.csv"))
    return pd.Series(v.CLOSE.values, index=pd.to_datetime(v.DATE, format="%m/%d/%Y"))


def part_a():
    d = pd.read_csv(os.path.join(ROOT, "data", "history", "index", "spy_daily.csv"), index_col=0, parse_dates=True)
    d = d[d.index < FINAL_TEST_START]
    r = np.log(d.Close).diff()
    base = pd.DataFrame({"move": r.shift(-1).abs(), "rv": r.rolling(20).std(),
                         "dist_ma50": (d.Close / d.Close.rolling(50).mean() - 1) / r.rolling(20).std(),
                         "vix_sd": vix("vix").reindex(d.index) / 100 / np.sqrt(252),
                         "vix9_sd": vix("vix9d").reindex(d.index) / 100 / np.sqrt(252)})
    print("Part A, S&P (SPY), out-of-sample 1997 to 2026-03")
    for K in (2, 3):
        f, p = walk_forward(d, K, 1997)
        S = base.join(f, how="inner").dropna(subset=["move", "rv", "dist_ma50"])
        turb = S[f"s{K - 1}"]
        print(f"  K = {K}, last fit: {describe(p, K, None)}")
        print(f"    share of days with turbulent-state probability > 0.5: {(turb > 0.5).mean():.0%}")
        for vcol in ("vix_sd", "vix9_sd"):
            T = S.dropna(subset=[vcol]).copy()
            T["lr"] = np.log(T.move + 1e-5) - np.log(T[vcol])
            T["lrv"] = np.log(T.rv) - np.log(T[vcol]); T["lvix"] = np.log(T[vcol])
            T["pt"] = T[f"s{K - 1}"] - 0.5
            ratio = (T.move / T[vcol]).values; hi = (T.pt > 0).values
            msg = (f"    {vcol[:-3].upper():<5} |move|/implied: turbulent {ratio[hi].mean():.3f} (n {hi.sum()}), "
                   f"other {ratio[~hi].mean():.3f}")
            for name, xs in (("alone", ["pt"]), ("with realized/implied, VIX level", ["lrv", "lvix", "pt"]),
                             ("plus 50-day trend", ["lrv", "lvix", "dist_ma50", "pt"])):
                Am = np.column_stack([np.ones(len(T))] + [T[c].values for c in xs]); y = T.lr.values
                b = np.linalg.lstsq(Am, y, rcond=None)[0][-1]
                bs = [np.linalg.lstsq(Am[i], y[i], rcond=None)[0][-1] for i in (blocks(len(T)) for _ in range(400))]
                lo, hi_ = np.percentile(bs, [2.5, 97.5])
                msg += f"\n      log(|move|/implied) on turbulent probability, {name}: {b:+.3f} ({lo:+.3f} to {hi_:+.3f})"
            print(msg)


# ---------------------------------------------------------------- part B, Bitcoin long shots
def boot_diff(df, flag, col, n=2000):
    g = df.groupby("day").apply(lambda x: pd.Series({"s1": x.loc[x[flag], col].sum(), "n1": x[flag].sum(),
                                                       "s0": x.loc[~x[flag], col].sum(), "n0": (~x[flag]).sum()})).values
    t = rng.multinomial(len(g), np.full(len(g), 1 / len(g)), size=n) @ g
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.nanpercentile(t[:, 0] / t[:, 1] - t[:, 2] / t[:, 3], [2.5, 97.5])


def part_b():
    d = pd.read_csv(os.path.join(ROOT, "data", "history", "crypto", "btc_daily.csv"), index_col=0, parse_dates=True)
    d = d[d.index < FINAL_TEST_START]
    q = pd.read_csv(os.path.join(ROOT, "research", "output", "explore_btc_sentiment.csv"))
    q = q[q.side == "down"].copy()
    q["sig"] = (q.fg <= 25) | (q.funding <= 0.0000149)
    print(f"\nPart B, Bitcoin: {len(q)} downside long-shot quotes on {q.day.nunique()} days ({q.day.min()} to {q.day.max()})")
    for K in (2, 3):
        f, p = walk_forward(d, K, 2017)
        print(f"  K = {K}, last fit: {describe(p, K, None)}")
        f.index = (f.index + pd.Timedelta(days=1)).strftime("%Y-%m-%d")   # day t's close -> settlement day t+1 (UTC)
        s = q.join(f, on="day")
        for col, name in ((f"s{K - 1}", "turbulent"), ("bear", "bearish")):
            if K == 2 and name == "bearish":
                continue
            s["hi"] = s[col] > 0.5
            for h in (1, 3):
                x = s[s.h == h].dropna(subset=[col]).copy()
                if x.hi.sum() < 10 or (~x.hi).sum() < 10:
                    print(f"    {name} {h}h: too few"); continue
                lo, hi_ = boot_diff(x, "hi", "over")
                print(f"    {name:<9} {h}h: overpricing {100 * x[x.hi].over.mean():+.2f}c ({x[x.hi].day.nunique()} days) vs "
                      f"{100 * x[~x.hi].over.mean():+.2f}c; difference {100 * (x[x.hi].over.mean() - x[~x.hi].over.mean()):+.2f}c "
                      f"({100 * lo:+.2f} to {100 * hi_:+.2f}); overlap with fear-or-funding days {x[x.hi].sig.mean():.0%}")
                for sg in (True, False):
                    y = x[x.sig == sg].copy()
                    if y.hi.sum() < 10 or (~y.hi).sum() < 10:
                        print(f"      within {'signal' if sg else 'non-signal'} days: too few ({y.hi.sum()} / {(~y.hi).sum()})"); continue
                    lo, hi_ = boot_diff(y, "hi", "over")
                    print(f"      within {'signal' if sg else 'non-signal':<10} days: {100 * y[y.hi].over.mean():+.2f}c vs "
                          f"{100 * y[~y.hi].over.mean():+.2f}c; difference ({100 * lo:+.2f} to {100 * hi_:+.2f}); "
                          f"selling it {100 * y[y.hi].pnl.mean():+.2f}c vs {100 * y[~y.hi].pnl.mean():+.2f}c, "
                          f"paid out {(y[y.hi].y == 0).mean():.1%} vs {(y[~y.hi].y == 0).mean():.1%}")


if __name__ == "__main__":
    part_a()
    part_b()
