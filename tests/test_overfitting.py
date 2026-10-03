"""Sanity checks: on pure noise the tools must say 'no edge'; on a real edge they must find it.
Run from the project root:  python3 -m tests.test_overfitting
"""
import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from robustness import sharpe, probabilistic_sharpe, deflated_sharpe, pbo_cscv, min_track_record_length

rng = np.random.default_rng(42)
T, N = 2520, 400                     # ten years of daily returns, 400 strategies

noise = rng.normal(0, 0.01, (T, N))
srs = noise.mean(0) / noise.std(0, ddof=1)
best = int(np.argmax(srs))
print(f"noise: best annualized Sharpe looks like {sharpe(noise[:, best]):.2f}")
psr = probabilistic_sharpe(noise[:, best])
dsr, sr0 = deflated_sharpe(noise[:, best], srs)
res = pbo_cscv(noise, n_blocks=10)
print(f"  naive PSR {psr:.3f} (fooled), deflated {dsr:.3f}, expected-max benchmark {sr0 * np.sqrt(252):.2f} ann.")
print(f"  PBO {res['pbo']:.2f} over {res['n_splits']} splits")
assert psr > 0.9, "the best of 400 noise strategies should look significant before deflation"
assert dsr < 0.5, "deflation should remove the illusion"
assert 0.35 < res["pbo"] < 0.75, "PBO on pure noise should sit near 0.5"

edge = noise.copy()
edge[:, :5] += 0.0012                # five strategies with a real ~1.9 annualized Sharpe
srs_e = edge.mean(0) / edge.std(0, ddof=1)
best_e = int(np.argmax(srs_e))
dsr_e, _ = deflated_sharpe(edge[:, best_e], srs_e)
res_e = pbo_cscv(edge, n_blocks=10)
print(f"edge: best is #{best_e} at {sharpe(edge[:, best_e]):.2f}, deflated {dsr_e:.3f}, PBO {res_e['pbo']:.2f}, "
      f"min track record {min_track_record_length(edge[:, best_e]):.0f} days")
assert best_e < 5 and dsr_e > 0.95 and res_e["pbo"] < 0.1
print("all checks passed")
