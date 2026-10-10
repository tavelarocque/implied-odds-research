"""Gatheral & Jacquier (2014): Durrleman's g(k) detects butterfly arbitrage in an SVI slice.
1. Their Example 3.1 (a, b, m, rho, sigma) = (-0.0410, 0.1331, 0.3586, 0.3060, 0.4153), t = 1, has negative g.
2. A sensible smile has g >= 0 everywhere.
3. Moving a smile to an earlier time (implied/crypto.at_time) cannot create butterfly arbitrage: for lam <= 1,
   g_lam(k) = g(k / sqrt(lam)) + (1 - lam) w'(k / sqrt(lam))^2 / 16 >= g.
"""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from implied.bl import Surface, svi_durrleman_g, svi_total_variance
from implied.crypto import at_time


def test_gj_example():
    a, b, m, rho, s = -0.0410, 0.1331, 0.3586, 0.3060, 0.4153          # paper's order: a, b, m, rho, sigma
    k = np.linspace(-1.5, 1.5, 3001)
    g = svi_durrleman_g(k, a, b, rho, m, s)                               # ours: a, b, rho, m, sigma
    assert g.min() < 0, g.min()
    surf = Surface(1.0, 1.0, 1.0, (a, b, rho, m, s), (-0.5, 0.5))
    assert surf.arb_check(width=12)["min_g"] < 0


def test_clean_smile():
    surf = Surface(5000.0, 1.0, 1 / 365, (0.00002, 0.004, -0.6, 0.002, 0.01), (-0.03, 0.02))
    c = surf.arb_check()
    assert c["min_g"] >= 0 and c["share_g_negative"] == 0 and c["lee_slope"] <= 2


def test_time_shift_keeps_no_arbitrage():
    rng = np.random.default_rng(3)
    for _ in range(200):
        p = (rng.uniform(0, 0.0005), rng.uniform(0.001, 0.05), rng.uniform(-0.9, 0.9), rng.uniform(-0.02, 0.02),
             rng.uniform(0.005, 0.05))
        s1 = Surface(80000.0, 1.0, 1 / 365, p, (-0.1, 0.1))
        g1 = s1.arb_check(width=6)["min_g"]
        if g1 < 0:
            continue
        for lam in (0.75, 0.5, 0.1):
            st = at_time(s1, lam / 365, 80000.0)
            assert st.arb_check(width=6)["min_g"] >= -1e-12, (p, lam)


if __name__ == "__main__":
    test_gj_example(); test_clean_smile(); test_time_shift_keeps_no_arbitrage(); print("ok")
