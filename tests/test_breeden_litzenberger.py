"""Breeden-Litzenberger must recover probabilities we know in advance before it touches real data.

1. Flat volatility: prices from Black-76, where P(S_T > K) = N(d2) exactly.
2. A skewed smile: prices generated from a known SVI smile; recovered range probabilities must match it.
3. The implied density must integrate to one, have mean equal to the forward, and carry no negative mass.
Quotes get bid/ask noise in every test, and the forward and discount factor are estimated, not given.
Run from the project root:  python3 -m tests.test_breeden_litzenberger
"""
import os, sys, math
import numpy as np
from scipy.stats import norm
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from implied import black_call, black_put, fit_surface, Surface

rng = np.random.default_rng(0)
F_TRUE, T, DF_TRUE = 7700.0, 5 / 365, math.exp(-0.04 * 5 / 365)
K = np.arange(7000, 8405, 5.0)
RANGES = [(None, 7500), (7500, 7600), (7600, 7650), (7650, 7700), (7700, 7725), (7725, 7750), (7750, 7800), (7800, 7900), (7900, None)]


def noisy(prices, half_spread=0.15):
    # mid = true price + quote noise, floor at a tick
    return np.maximum(prices + rng.uniform(-half_spread, half_spread, size=prices.shape), 0.05)


def check(name, surf, truth, tol):
    worst = 0.0
    for lo, hi in RANGES:
        p, t = surf.prob_between(lo, hi), truth(lo, hi)
        worst = max(worst, abs(p - t))
    print(f"{name}: forward {surf.F:.2f} (true {F_TRUE}), DF {surf.DF:.6f} (true {DF_TRUE:.6f}), "
          f"worst range-probability error {100 * worst:.2f} pp")
    assert abs(surf.F - F_TRUE) < 0.5 and abs(surf.DF - DF_TRUE) < 2e-4, "forward / discount factor off"
    assert worst < tol, f"range probabilities off by {worst:.4f}"
    c = surf.checks()
    print(f"   density: mass {c['mass']:.4f}, mean {c['mean']:.2f}, negative mass {c['negative_mass']:.5f}")
    assert abs(c["mass"] - 1) < 0.01 and abs(c["mean"] - F_TRUE) < 2 and c["negative_mass"] < 0.002


# 1. Flat volatility: the exact answer is a difference of N(d2) terms.
sig = 0.16
calls, puts = black_call(F_TRUE, K, T, sig, DF_TRUE), black_put(F_TRUE, K, T, sig, DF_TRUE)
surf = fit_surface(K, noisy(calls), noisy(puts), T, spot_guess=7690)

def flat_truth(lo, hi):
    above = lambda x: 1.0 if x is None else float(norm.cdf((math.log(F_TRUE / x) - 0.5 * sig ** 2 * T) / (sig * math.sqrt(T))))
    return above(lo) - (0.0 if hi is None else above(hi))

check("flat vol", surf, flat_truth, tol=0.005)

# 2. Skewed smile: the truth is the known SVI surface, priced and differentiated without noise.
true_params = (0.00002, 0.004, -0.75, 0.002, 0.012)
truth_surface = Surface(F_TRUE, DF_TRUE, T, true_params, (-1, 1))
sig_k = truth_surface.sigma(K)
calls, puts = black_call(F_TRUE, K, T, sig_k, DF_TRUE), black_put(F_TRUE, K, T, sig_k, DF_TRUE)
surf = fit_surface(K, noisy(calls), noisy(puts), T, spot_guess=7690)
check("skewed smile", surf, lambda lo, hi: truth_surface.prob_between(lo, hi), tol=0.01)
print("all checks passed")
