"""The smile fit must stay a real density when one wing has almost no quotes.

Found on live Nasdaq-100 data (Oct 2026): cheap upside calls have wide relative spreads and get filtered out, so the
fit saw strikes only from -2% to +1% around the forward. The unconstrained SVI fit then bent the upside wing into
an impossible shape: density mass 2.2 with negative probability beyond +4%. A second failure on the same data:
put-call parity gave a discount factor above 1 for a 2-day expiry, and the fit refused to run.

This rebuilds both conditions from a known smile and requires:
  1. a density that integrates to ~1 with no negative mass, out to 6 standard deviations;
  2. P(S_T > F) within 2pp of the truth;
  3. a forward estimate even when the parity slope comes out slightly above 1.

Run from the project root:  python3 -m tests.test_sparse_wing
"""
import os, sys, math
import numpy as np
from scipy.stats import norm

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from implied import black_call, black_put, fit_surface
from implied.bl import estimate_forward

rng = np.random.default_rng(1)
F, T, DF = 30800.0, 2 / 365, math.exp(-0.04 * 2 / 365)
failed = []


def true_sigma(K):
    k = np.log(K / F)
    return np.clip(0.14 - 1.2 * k + 6.0 * k ** 2, 0.08, None)     # a typical equity-index skew


# 1-2. Quotes from -6% to only +1.2%, with noise proportional to a realistic spread.
K = F * np.exp(np.arange(-0.06, 0.0121, 0.0015))
sig = true_sigma(K)
C, P = black_call(F, K, T, sig, DF), black_put(F, K, T, sig, DF)
spread = np.clip(0.04 * np.minimum(C, P), 0.5, None)
Cn = np.maximum(C + rng.uniform(-0.5, 0.5, K.size) * spread, 0.05)
Pn = np.maximum(P + rng.uniform(-0.5, 0.5, K.size) * spread, 0.05)
surf = fit_surface(K, Cn, Pn, T, spot_guess=F, weights=1 / spread)
c = surf.checks()
ok1 = abs(c["mass"] - 1) < 0.02 and c["negative_mass"] < 0.005
print(f"{'PASS' if ok1 else 'FAIL'}  sparse upside: density mass {c['mass']:.3f}, negative mass {c['negative_mass']:.4f}")
if not ok1:
    failed.append("sparse upside density")

# Truth from the true prices: P(S_T > K) = -(1/DF) dC/dK. With a skew this is NOT N(d2): a smile that falls with
# the strike adds -vega * dsigma/dK, which pushes P(S_T > F) above 50%.
h = F * 1e-4
Kh = np.array([F - h, F + h])
Ch = black_call(F, Kh, T, true_sigma(Kh), DF)
p_true = float(-(Ch[1] - Ch[0]) / (2 * h) / DF)
p_fit = float(surf.prob_above(F))
ok2 = abs(p_fit - p_true) < 0.02
print(f"{'PASS' if ok2 else 'FAIL'}  P(S_T > F): fitted {p_fit:.3f}, true {p_true:.3f}")
if not ok2:
    failed.append("P(S_T > F)")

# 3. A parity slope that comes out above 1 (DF = 1.001) on a short expiry must still give the right forward.
Kp = np.arange(F * 0.97, F * 1.03, 25.0)
y = 1.001 * (F - Kp) + rng.normal(0, 1.0, Kp.size)               # C - P with a slightly-too-steep slope
try:
    F_hat, DF_hat = estimate_forward(Kp, y, np.zeros_like(y), spot_guess=F, T=T)
    ok3 = abs(F_hat / F - 1) < 5e-4 and DF_hat <= 1.0
    print(f"{'PASS' if ok3 else 'FAIL'}  steep parity slope: forward {F_hat:,.1f} (true {F:,.1f}), DF {DF_hat:.5f}")
except ValueError as e:
    ok3 = False
    print(f"FAIL  steep parity slope: {e}")
if not ok3:
    failed.append("steep parity slope")

sys.exit(1 if failed else 0)
