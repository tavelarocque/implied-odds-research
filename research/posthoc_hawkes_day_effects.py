"""POST-HOC (not pre-registered; see the addendum in research/PREREGISTRATION_HAWKES.md).

The pre-registered fit shares one baseline across all days. If some days are busy all day and others quiet, the
shared baseline under-predicts busy days from start to finish, and the excitation term (which tracks recent activity)
picks up the slack: on simulated data with no self-excitation and day levels varying by ~50%, the fit returns n = 0.999.
This refits with a multiplicative level per day, which removes that confound (tests/test_hawkes.py, check 4).

Run from the project root:  python3 research/posthoc_hawkes_day_effects.py [n_boot]
Output: research/output/hawkes/posthoc_day_effects.txt
"""
import os, sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "research"))
N_BOOT = int(sys.argv[1]) if len(sys.argv) > 1 else 500
sys.argv = sys.argv[:1]
from hawkes_activity import load, SERIES, COUNTS, OUT, ci
from microstructure.hawkes import fit_day_effects

_DATA = None


def _init(d):
    global _DATA
    _DATA = d


def _boot(seed):
    rng = np.random.default_rng(seed)
    D = next(iter(_DATA.values())).shape[0]
    idx = rng.integers(0, D, D)
    return {k: (r["n"], r["half_life"]) for k, N in _DATA.items() for r in [fit_day_effects(N[idx])]}


def main():
    raw = {s: load(s) for s in SERIES}
    dates = sorted(set(raw["KXINX"]) & set(raw["KXNASDAQ100"]))
    data = {(s, c): np.array([raw[s][d][c] for d in dates]) for s in SERIES for c in COUNTS}
    lines = [f"POST-HOC: day effects added. {len(dates)} days, {N_BOOT} day-bootstrap resamples.", "",
             "How much do days differ in overall level? (daily total: standard deviation / mean; Poisson alone would give "
             "about 1/sqrt(mean))"]
    for (s, c), N in data.items():
        tot = N.sum(1)
        lines.append(f"  {SERIES[s]:<10} {c:<8} daily total mean {tot.mean():7.0f}   sd/mean {tot.std() / tot.mean():.2f}   "
                     f"Poisson would be {1 / np.sqrt(tot.mean()):.2f}")
    point = {k: fit_day_effects(N) for k, N in data.items()}
    with ProcessPoolExecutor(initializer=_init, initargs=(data,)) as ex:
        boots = list(ex.map(_boot, range(N_BOOT), chunksize=4))
    lines += ["", "Branching ratio with day effects (same 0.10 bar as the pre-registered rule, applied post hoc):"]
    for k, r in point.items():
        lo, hi = ci([b[k][0] for b in boots]); hlo, hhi = ci([b[k][1] for b in boots])
        v = "self-exciting" if lo > 0.10 else "no meaningful self-excitation" if hi < 0.10 else "inconclusive"
        lines.append(f"  {SERIES[k[0]]:<10} {k[1]:<8} n = {r['n']:.3f} ({lo:.3f} to {hi:.3f})   half-life {r['half_life']:.2f} min "
                     f"({hlo:.2f} to {hhi:.2f})   -> {v}")
    lines.append("\nS&P minus Nasdaq, paired:")
    for c in COUNTS:
        d = [b[("KXINX", c)][0] - b[("KXNASDAQ100", c)][0] for b in boots]
        lo, hi = ci(d)
        lines.append(f"  {c:<8} {point[('KXINX', c)]['n'] - point[('KXNASDAQ100', c)]['n']:+.3f} ({lo:+.3f} to {hi:+.3f})")
    txt = "\n".join(lines)
    print(txt)
    open(os.path.join(OUT, "posthoc_day_effects.txt"), "w").write(txt + "\n")


if __name__ == "__main__":
    main()
