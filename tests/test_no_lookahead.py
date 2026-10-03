"""Every strategy must be blind to the future.

For each rule, mode and sizing: compute positions, then scramble every price AFTER day t and recompute.
Positions up to and including day t+1 (which are set by information through day t) must not change.
If any rule peeks ahead, even by one day, this fails and names it.
Run from the project root:  python3 -m tests.test_no_lookahead
"""
import os, sys
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategies import rules, positions

rng = np.random.default_rng(5)
idx = pd.bdate_range("2010-01-01", periods=900)
px = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, len(idx)))), index=idx)
checked, leaks = 0, []
for t in [5, 30, 260, 600]:                      # include points inside the warm-up windows
    cut = idx[t]
    future = px.copy()
    future[future.index > cut] *= np.exp(np.cumsum(rng.normal(0, 0.05, (future.index > cut).sum())))
    r0, r1 = px.pct_change(), future.pct_change()
    for name, fn in rules():
        a, b = fn(px), fn(future)
        for mode in ("ls", "lo"):
            for sizing in ("flat", "vt"):
                p0 = positions(a, r0, mode, sizing).iloc[: t + 2]     # days 0..t+1
                p1 = positions(b, r1, mode, sizing).iloc[: t + 2]
                checked += 1
                if not np.allclose(p0.values, p1.values, equal_nan=True):
                    leaks.append(f"{name}:{mode}:{sizing} at t={t}")
print(f"checked {checked} rule/mode/sizing/date combinations")
assert not leaks, "look-ahead detected in: " + ", ".join(leaks[:10])
print("no look-ahead: all checks passed")
