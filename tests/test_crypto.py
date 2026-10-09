"""Checks for implied/crypto.py: parsing, and that moving a smile in time keeps its shape in standard deviations."""
import math, os, sys
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from implied.bl import Surface, svi_total_variance
from implied.crypto import parse_instrument, at_time


def test_parse():
    e, k, cp = parse_instrument("BTC-10OCT26-84500-C")
    assert e == datetime(2026, 10, 10, 8, tzinfo=timezone.utc) and k == 84500 and cp == "C"
    assert parse_instrument("BTC-9OCT26-80000-P")[0].day == 9


def test_at_time_shape():
    s1 = Surface(80000.0, 1.0, 1 / 365, (0.0001, 0.01, -0.3, 0.0, 0.02), (-0.08, 0.08))
    st = at_time(s1, 0.25 / 365, 80000.0)
    lam = 0.25
    for z in (-1.5, -0.5, 0.0, 0.7, 2.0):                    # same standardized moneyness -> same implied vol
        k1 = z * math.sqrt(svi_total_variance(0.0, *s1.params))
        kt = k1 * math.sqrt(lam)
        assert abs(svi_total_variance(kt, *st.params) - lam * svi_total_variance(k1, *s1.params)) < 1e-15
    assert abs(float(st.prob_above(80000.0)) - float(s1.prob_above(80000.0))) < 0.01   # ATM stays near 50%
    c = st.checks()
    assert abs(c["mass"] - 1) < 0.01 and c["negative_mass"] < 1e-3
    assert at_time(s1, 2 / 365, 80000.0) is s1                 # later than T1: unchanged


if __name__ == "__main__":
    test_parse(); test_at_time_shape(); print("ok")
