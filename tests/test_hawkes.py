"""The Hawkes fit must recover parameters we know, and must not mistake a predictable ramp for self-excitation.

1. Self-exciting data (n = 0.5, half-life 3 minutes) on a ramping baseline: the fit recovers n within 0.05 and the
   half-life within 0.75 minutes, on three independent simulations.
2. Pure ramp, no self-excitation (n = 0): with the fitted baseline, n stays below 0.05 on three simulations; with a
   constant baseline the ramp masquerades as self-excitation (n above 0.3). This is the confound the analysis removes.
3. The analytic gradient matches a finite difference.
4. (Added after the pre-registration, see its addendum.) Days that differ in overall level but have no clustering
   inside them: the shared-baseline fit returns n near 1, the day-effects fit returns n below 0.05, and with real
   self-excitation (n = 0.5) the day-effects fit stays within 0.1 (it is biased slightly low).

Run from the project root:  python3 -m tests.test_hawkes
"""
import os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from microstructure.hawkes import simulate, fit, fit_day_effects, basis, _nll_grad, _nll_grad_days

failed = []


def check(ok, msg):
    print(f"{'PASS' if ok else 'FAIL'}  {msg}")
    if not ok:
        failed.append(msg)


T = 360
ramp = 1 + 3 * (np.arange(T) / T) ** 3            # activity climbs into the close
ramp = ramp / ramp.mean()
phi = 0.5 ** (1 / 3)                              # half-life 3 minutes

for seed in range(3):
    rng = np.random.default_rng(seed)
    r = fit(simulate(110, 2.0 * ramp, n=0.5, phi=phi, rng=rng))
    check(abs(r["n"] - 0.5) < 0.05 and abs(r["half_life"] - 3) < 0.75,
          f"seed {seed}: recovers n = 0.5, half-life 3 min: n = {r['n']:.3f}, half-life {r['half_life']:.2f} min")

for seed in range(3):
    rng = np.random.default_rng(100 + seed)
    N0 = simulate(110, 3.0 * ramp, n=0.0, phi=0.5, rng=rng)
    r0 = fit(N0)
    check(r0["n"] < 0.05, f"seed {seed}: no self-excitation, fitted baseline: n = {r0['n']:.3f}")
    if seed == 0:
        rf = fit(N0, K=1)
        check(rf["n"] > 0.3, f"no self-excitation, constant baseline (the confound): n = {rf['n']:.3f}")

rng = np.random.default_rng(7)
N = simulate(20, 2.0 * ramp, n=0.4, phi=0.7, rng=rng)
B = basis(T, 6)
x = np.r_[0.3, 0.2, rng.normal(0, 0.1, 6)]
f, g = _nll_grad(x, N, B)
num = np.array([(_nll_grad(x + 1e-5 * e, N, B)[0] - _nll_grad(x - 1e-5 * e, N, B)[0]) / 2e-5 for e in np.eye(len(x))])
check(np.allclose(g, num, rtol=1e-3, atol=1e-1), f"gradient matches finite difference (max abs diff {abs(g - num).max():.2e})")

rng = np.random.default_rng(11)
lv = np.exp(rng.normal(0, 0.5, 110))                        # busy and quiet days
N0 = np.vstack([simulate(1, 3 * l * ramp, n=0.0, phi=0.5, rng=rng) for l in lv])
N5 = np.vstack([simulate(1, 2 * l * ramp, n=0.5, phi=phi, rng=rng) for l in lv])
p0, d0, d5 = fit(N0)["n"], fit_day_effects(N0)["n"], fit_day_effects(N5)["n"]
check(p0 > 0.9, f"day-level heterogeneity, no self-excitation, shared baseline (the second confound): n = {p0:.3f}")
check(d0 < 0.05, f"day-level heterogeneity, no self-excitation, day effects: n = {d0:.3f}")
check(abs(d5 - 0.5) < 0.1, f"day-level heterogeneity, n = 0.5, day effects: n = {d5:.3f}")
B = basis(T, 5)
N = simulate(8, 2.0 * ramp, n=0.4, phi=0.7, rng=rng)
x = np.r_[0.3, 0.2, rng.normal(0, 0.1, 5), rng.normal(0, 0.1, 7)]
f, g = _nll_grad_days(x, N, B)
num = np.array([(_nll_grad_days(x + 1e-5 * e, N, B)[0] - _nll_grad_days(x - 1e-5 * e, N, B)[0]) / 2e-5 for e in np.eye(len(x))])
check(np.allclose(g, num, rtol=1e-3, atol=1e-1), f"day-effects gradient matches finite difference (max abs diff {abs(g - num).max():.2e})")

sys.exit(1 if failed else 0)
