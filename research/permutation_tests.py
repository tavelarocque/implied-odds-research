# %% [markdown]
# # Masters' permutation tests on strategy discovery
#
# Third independent check on the strategy-discovery search, next to the deflated Sharpe ratio and PBO.
#
# 1. In-sample permutation test: search all ~2,000 rules on 1999-2012 and keep the best Sharpe. Then do the same
#    search on 1,000 shuffled histories of the same period. If shuffled data produces winners as good as the real
#    winner, the real winner's Sharpe is search luck.
# 2. Walk-forward test: every month, pick the rule with the best Sharpe over the trailing 5 years and trade it for
#    the next month. This is how the search would really be used.
# 3. Walk-forward permutation test: the same walk-forward on 1,000 histories shuffled after the first training
#    window. Could a worthless search have walked forward this well?
#
# Data ends before the locked holdout (research/config.py). Run from the project root:
#   python3 research/permutation_tests.py [n_permutations]      (default 1000; about 10 minutes on 8 cores)

# %%
import os, sys, time
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
from config import FINAL_TEST_START
from robustness.permutation import permute_prices, permutation_pvalue, run_permutations
from strategies import build_library

PRICES = os.path.join(ROOT, "data", "history", "etf", "prices.csv.gz")
OUT = os.path.join(ROOT, "research", "output", "permutation_tests")
SPLIT = "2013-01-01"          # same in-sample period as research/strategy_discovery.py
WARMUP = 260                  # rules need a year of history before they trade
TRAIN = 5 * 252               # walk-forward: select on the trailing 5 years
STEP = 21                     # ... and re-select every month
COST_BPS = 2.0


def ann_sharpe(x):
    x = np.asarray(x, float)
    sd = x.std()
    return x.mean() / sd * np.sqrt(252) if sd > 0 else np.nan


def best_insample_sharpe(px):
    """The whole search on one history: build every rule, keep the best annualized Sharpe."""
    R, _ = build_library(px, cost_bps=COST_BPS)
    R = R.iloc[WARMUP:].values
    sd = R.std(axis=0)
    ok = sd > 0
    return float((R[:, ok].mean(axis=0) / sd[ok]).max() * np.sqrt(252))


def walk_forward(px, return_detail=False):
    """Monthly re-selection of the rule with the best trailing-5-year Sharpe; returns the out-of-sample Sharpe."""
    R, _ = build_library(px, cost_bps=COST_BPS)
    R = R.iloc[WARMUP:]
    X = R.values
    c1 = np.vstack([np.zeros(X.shape[1]), np.cumsum(X, axis=0)])
    c2 = np.vstack([np.zeros(X.shape[1]), np.cumsum(X ** 2, axis=0)])
    oos, picks = [], []
    for i in range(TRAIN, len(X), STEP):
        m = (c1[i] - c1[i - TRAIN]) / TRAIN
        v = (c2[i] - c2[i - TRAIN]) / TRAIN - m ** 2
        score = np.where(v > 1e-14, m / np.sqrt(np.maximum(v, 1e-14)), -np.inf)
        j = int(np.argmax(score))
        oos.append(X[i:i + STEP, j])
        picks.append((R.index[i], R.columns[j]))
    oos = np.concatenate(oos)
    if return_detail:
        return ann_sharpe(oos), pd.Series(oos, index=R.index[TRAIN:TRAIN + len(oos)]), picks
    return ann_sharpe(oos)


def histogram(ax, perms, real, title, xlabel):
    ax.hist(perms, bins=40, color="#4a6fa5", alpha=.8, label="shuffled histories")
    ax.axvline(real, color="#b8520a", lw=2, label=f"real data: {real:.2f}")
    ax.set_title(title); ax.set_xlabel(xlabel); ax.set_ylabel("Shuffled histories"); ax.legend(frameon=False, fontsize=8)


if __name__ == "__main__":
    N = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    os.makedirs(OUT, exist_ok=True)
    px_all = pd.read_csv(PRICES, index_col=0, parse_dates=True).dropna()
    px_all = px_all.loc[px_all.index < FINAL_TEST_START]
    px_is = px_all.loc[px_all.index < SPLIT]
    print(f"{px_all.shape[1]} ETFs, {px_all.index[0].date()} to {px_all.index[-1].date()} (holdout from {FINAL_TEST_START} excluded)")

    # %% 1. In-sample permutation test
    t0 = time.time()
    real_is = best_insample_sharpe(px_is)
    perm_is = run_permutations(best_insample_sharpe, px_is, n=N, start=0, seed=1)
    p_is = permutation_pvalue(real_is, perm_is)
    print(f"\n[1] In-sample, {px_is.index[0].year}-{px_is.index[-1].year}: best Sharpe on real data {real_is:.2f}; "
          f"on shuffled data median {np.median(perm_is):.2f}, 95th pct {np.percentile(perm_is, 95):.2f}")
    print(f"    p = {p_is:.3f}  ({N} shuffles, {time.time() - t0:.0f}s)  "
          f"-> {'the winner beats search luck' if p_is < 0.01 else 'the winner is not distinguishable from search luck'}")

    # %% 2-3. Walk-forward and its permutation test
    t0 = time.time()
    real_wf, wf_ret, picks = walk_forward(px_all, return_detail=True)
    start = WARMUP + TRAIN                     # shuffle only after the first training window
    perm_wf = run_permutations(walk_forward, px_all, n=N, start=start, seed=2)
    p_wf = permutation_pvalue(real_wf, perm_wf)
    spy = np.log(px_all["SPY"]).diff().reindex(wf_ret.index)
    spy_sr = ann_sharpe(px_all["SPY"].pct_change().reindex(wf_ret.index).dropna())
    n_rules = len({p[1] for p in picks})
    print(f"\n[2] Walk-forward, {wf_ret.index[0].date()} to {wf_ret.index[-1].date()}: re-selected {len(picks)} times, "
          f"{n_rules} different rules used; out-of-sample Sharpe {real_wf:.2f} (SPY buy-and-hold {spy_sr:.2f})")
    print(f"[3] Walk-forward permutation test: shuffled median {np.median(perm_wf):.2f}, 95th pct {np.percentile(perm_wf, 95):.2f}; "
          f"p = {p_wf:.3f}  ({N} shuffles, {time.time() - t0:.0f}s)")

    pd.DataFrame({"perm_insample_best_sharpe": perm_is, "perm_walkforward_sharpe": perm_wf}).to_csv(
        os.path.join(OUT, "permutations.csv"), index=False)
    pd.DataFrame([{"test": "in-sample", "real": real_is, "p": p_is, "n": N},
                  {"test": "walk-forward", "real": real_wf, "p": p_wf, "n": N, "spy_sharpe": spy_sr}]).to_csv(
        os.path.join(OUT, "summary.csv"), index=False)

    fig, axes = plt.subplots(1, 3, figsize=(16, 4.4))
    histogram(axes[0], perm_is, real_is, f"In-sample permutation test (p = {p_is:.3f})",
              f"Best Sharpe of the search, {px_is.index[0].year}-{px_is.index[-1].year}")
    ax = axes[1]
    ax.plot(wf_ret.cumsum().index, wf_ret.cumsum().values, color="#b8520a", label=f"walk-forward search (Sharpe {real_wf:.2f})")
    ax.plot(spy.cumsum().index, spy.cumsum().values, color="#555", lw=1, label=f"SPY buy-and-hold (Sharpe {spy_sr:.2f})")
    ax.set_title("Walk-forward: re-pick the best rule every month"); ax.set_ylabel("Cumulative log return")
    ax.legend(frameon=False, fontsize=8)
    histogram(axes[2], perm_wf, real_wf, f"Walk-forward permutation test (p = {p_wf:.3f})", "Walk-forward Sharpe")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "permutation_tests.png"), dpi=150)
    print(f"\nWritten to {OUT}")
