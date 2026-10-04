"""The permutation test must keep what it should keep, destroy what it should destroy, and tell signal from noise.

1. A shuffled history keeps the first and last price, the return distribution, and same-day correlation.
2. Rows before `start` are untouched (the walk-forward test relies on this).
3. Pure noise: the best of 20 momentum lookbacks is NOT special (p above 1%; under noise p is uniform).
4. A planted trend-persistence pattern: the best momentum rule IS special, p-value below 1%.

Run from the project root:  python3 -m tests.test_permutation
"""
import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from robustness.permutation import permute_prices, permutation_pvalue, run_permutations

failed = []


def check(ok, msg):
    print(f"{'PASS' if ok else 'FAIL'}  {msg}")
    if not ok:
        failed.append(msg)


rng = np.random.default_rng(3)
n = 2500
idx = pd.bdate_range("2010-01-01", periods=n)
z = rng.standard_normal((n, 2))
lr = np.column_stack([0.01 * z[:, 0], 0.01 * (0.8 * z[:, 0] + 0.6 * z[:, 1])])   # correlation 0.8
px = pd.DataFrame(100 * np.exp(np.cumsum(lr, axis=0)), index=idx, columns=["A", "B"])

# 1-2
pp = permute_prices(px, start=0, rng=np.random.default_rng(1))
r0, r1 = np.diff(np.log(px.values), axis=0), np.diff(np.log(pp.values), axis=0)
check(np.allclose(pp.iloc[0], px.iloc[0]) and np.allclose(pp.iloc[-1], px.iloc[-1]), "first and last price unchanged")
check(np.allclose(np.sort(r0[:, 0]), np.sort(r1[:, 0])), "same set of daily returns, only reordered")
check(abs(np.corrcoef(r1.T)[0, 1] - np.corrcoef(r0.T)[0, 1]) < 1e-9, "same-day correlation between markets preserved")
pw = permute_prices(px, start=1000, rng=np.random.default_rng(1))
check(np.allclose(pw.iloc[:1001], px.iloc[:1001]) and not np.allclose(pw.iloc[1001:], px.iloc[1001:]),
      "rows before the start index untouched, rows after shuffled")


# 3-4: a small "search": best annualized Sharpe over 20 momentum lookbacks, long/short on the sign of past return
def best_momentum(prices):
    r = np.log(prices["A"]).diff()
    best = -np.inf
    for k in range(1, 21):
        pos = np.sign(r.rolling(k).sum()).shift(1)
        s = (pos * r).dropna()
        if s.std() > 0:
            best = max(best, s.mean() / s.std() * np.sqrt(252))
    return best


noise = pd.DataFrame({"A": 100 * np.exp(np.cumsum(0.01 * rng.standard_normal(n)))}, index=idx)
p_noise = permutation_pvalue(best_momentum(noise), run_permutations(best_momentum, noise, n=200, seed=5, workers=1))
check(p_noise > 0.01, f"pure noise: best-of-20 momentum not significant (p = {p_noise:.3f})")

e = np.zeros(n)
eps = 0.01 * rng.standard_normal(n)
for t in range(1, n):
    e[t] = 0.15 * e[t - 1] + eps[t]                           # returns persist: real, exploitable momentum
trend = pd.DataFrame({"A": 100 * np.exp(np.cumsum(e))}, index=idx)
p_trend = permutation_pvalue(best_momentum(trend), run_permutations(best_momentum, trend, n=200, seed=5, workers=1))
check(p_trend < 0.01, f"planted trend persistence: detected (p = {p_trend:.3f})")

sys.exit(1 if failed else 0)
