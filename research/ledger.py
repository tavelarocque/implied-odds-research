"""Project-wide multiple-testing ledger (Harvey & Liu 2015, "Backtesting").

Every inferential claim the project has made so far is one row of research/ledger_claims.csv. The list was committed
before this script was first run, so membership was fixed before any adjusted number existed. Pre-registered verdicts
still pending (layers 5, 7, 7b, Bitcoin layer 5, 11 and 11b) are not in it; they enter when they are decided.

p-values: where a script reported one (permutation / Monte Carlo / exact), it is used as is. Where only an estimate
and a 95% interval were reported, p is approximated two-sided from a normal with standard error = width / 3.92: rough
for skewed bootstrap intervals, and stated as such. Families that were already summarized as "k of n comparisons
passed" enter as one row with a binomial p.

Adjustments: Holm (controls the chance of any false positive) and BHY (Benjamini-Hochberg-Yekutieli, controls the false
discovery rate under any dependence; Harvey & Liu's recommendation). Sensitivity: the same with the number of tests
doubled, for comparisons tried but never written down.
"""
import os
import numpy as np
import pandas as pd
from scipy.stats import norm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def holm(p, M=None):
    p = np.asarray(p); M = M or len(p); o = np.argsort(p); out = np.empty(len(p)); run = 0
    for k, i in enumerate(o):
        run = max(run, (M - k) * p[i]); out[i] = min(run, 1)
    return out


def bhy(p, M=None):
    p = np.asarray(p); n = len(p); M = M or n; c = (1 / np.arange(1, M + 1)).sum()
    o = np.argsort(p); out = np.empty(n); prev = 1.0
    for k in range(n - 1, -1, -1):
        i = o[k]; prev = min(prev, M * c / (k + 1) * p[i]); out[i] = min(prev, 1)
    return out


def main():
    d = pd.read_csv(os.path.join(ROOT, "research", "ledger_claims.csv"))
    ci = d.kind == "ci"
    se = (d.hi - d.lo) / 3.92
    d.loc[ci, "p"] = 2 * (1 - norm.cdf(np.abs((d.est - d["null"]) / se)))[ci]
    d["p"] = d.p.clip(lower=1e-6)
    d["holm"], d["bhy"] = holm(d.p), bhy(d.p)
    d["holm_2x"], d["bhy_2x"] = holm(d.p, 2 * len(d)), bhy(d.p, 2 * len(d))
    d = d.sort_values("p")
    print(f"{len(d)} claims. Raw p < 0.05: {(d.p < 0.05).sum()}; survive Holm: {(d.holm < 0.05).sum()}; "
          f"survive BHY: {(d.bhy < 0.05).sum()}; BHY with tests doubled: {(d.bhy_2x < 0.05).sum()}\n")
    print(f"{'id':<5} {'p':>8} {'Holm':>7} {'BHY':>7} {'BHY2x':>7}  claim")
    for r in d.itertuples():
        mark = "**" if r.bhy < 0.05 else ("* " if r.p < 0.05 else "  ")
        print(f"{r.id:<5} {r.p:8.4f} {r.holm:7.3f} {r.bhy:7.3f} {r.bhy_2x:7.3f} {mark}{r.claim}")
    d.to_csv(os.path.join(ROOT, "research", "output", "ledger.csv"), index=False)


if __name__ == "__main__":
    main()
