"""The ladder functions must turn Kalshi range quotes into correct probabilities and correct trade costs.
Run from the project root:  python3 -m tests.test_kalshi_ladder
"""
import os, sys, math
import numpy as np
from scipy.stats import norm
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from implied import make_ladder, prob_above, basket, basket_cost, kalshi_fee

# A ladder priced exactly from a normal distribution, mean 7700, sd 40, 25-point ranges, zero spread.
mu, sd = 7700.0, 40.0
edges = np.arange(7500, 7925, 25.0)
rows = [{"strike_type": "less", "floor_strike": None, "cap_strike": edges[0], "p": norm.cdf(edges[0], mu, sd)}]
for a, b in zip(edges[:-1], edges[1:]):
    rows.append({"strike_type": "between", "floor_strike": a, "cap_strike": b, "p": norm.cdf(b, mu, sd) - norm.cdf(a, mu, sd)})
rows.append({"strike_type": "greater", "floor_strike": edges[-1], "cap_strike": None, "p": 1 - norm.cdf(edges[-1], mu, sd)})
for r in rows:
    r["bid"] = r["ask"] = r["p"]
lad = make_ladder(rows)

# 1. On a range boundary the answer is exact.
for K in (7650, 7700, 7775):
    got, want = prob_above(lad, K), 1 - norm.cdf(K, mu, sd)
    assert abs(got - want) < 1e-9, (K, got, want)
# 2. Inside a range, flat-density interpolation is close to the truth.
worst = max(abs(prob_above(lad, K) - (1 - norm.cdf(K, mu, sd))) for K in np.arange(7600, 7800, 3.7))
print(f"prob_above: exact on boundaries, worst interpolation error inside a range {100 * worst:.2f} pp")
assert worst < 0.01
# 3. Normalization: inflating every quote by the same spread does not change the probability.
lad2 = make_ladder([{**r, "bid": max(r["p"] - 0.01, 0), "ask": r["p"] + 0.01} for r in rows])
assert abs(prob_above(lad2, 7712) - prob_above(lad, 7712)) < 0.02

# 4. The up basket covers every range that could pay when close > K, including the one containing K.
b = basket(lad, 7712, "up")
assert b.lo.min() == 7700 and np.isinf(b.hi.max())
b = basket(lad, 7712, "down")
assert np.isinf(-b.lo.min()) and b.hi.max() == 7725

# 5. Fees: per-contract rate, and Kalshi's round-up on a one-contract order.
assert abs(kalshi_fee(0.5) - 0.0175) < 1e-12 and kalshi_fee(0.5, contracts=1) == 0.02 and kalshi_fee(0.02, contracts=1) == 0.01
cost, n = basket_cost(lad, 7712, "up")
assert abs(cost - (b_up := basket(lad, 7712, "up")).ask.sum() - sum(kalshi_fee(a) for a in b_up.ask)) < 1e-12 and n == len(b_up)
# 6. A contract with no ask can't be bought, so the basket has no price.
rows3 = [dict(r) for r in rows]; rows3[-3]["ask"] = None
assert math.isnan(basket_cost(make_ladder(rows3), 7712, "up")[0])
# 7. ...but the probability still works: an unquoted far-out range is valued at its bid.
rows3[-3]["bid"] = 0.0
assert np.isfinite(prob_above(make_ladder(rows3), 7712))
print("all checks passed")
