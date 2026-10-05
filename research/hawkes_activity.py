"""Pre-registered Hawkes study (research/PREREGISTRATION_HAWKES.md): is activity on Kalshi's S&P 500 and Nasdaq-100
ladders self-exciting?

Run from the project root:
    SMOKE=1 python3 research/hawkes_activity.py      data quality only, no fitting
    python3 research/hawkes_activity.py [n_boot]     full analysis (default 1,000 day-bootstrap resamples)
Output: research/output/hawkes/
"""
import gzip, json, os, re, sys, math
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "research"))
from microstructure.hawkes import fit, HALF_LIFE_CAP
from config import exploratory

SERIES = {"KXINX": "S&P 500", "KXNASDAQ100": "Nasdaq-100"}
COUNTS = ("activity", "trades")
START, T, LOWER = "2025-10-16", 360, 0.10
N_BOOT = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
SMOKE = os.environ.get("SMOKE") == "1"
KH = os.path.join(ROOT, "data", "history", "kalshi")
OUT = os.path.join(ROOT, "research", "output", "hawkes")
ts = lambda s: int(datetime.fromisoformat(re.sub(r"\.\d+", "", s.replace("Z", "+00:00"))).timestamp())


def load(series):
    """Returns {date: {"activity": counts[T], "trades": counts[T]}}."""
    mk = pd.DataFrame([json.loads(l) for l in gzip.open(os.path.join(KH, f"markets_{series}.jsonl.gz"), "rt")])
    mk = mk[mk.result.isin(["yes", "no"])].copy()
    mk["day"] = mk.close_time.str[:10]
    mk = mk[exploratory(mk.day) & (mk.day >= START)]
    out = {}
    for day, g in mk.groupby("day"):
        close = ts(g.close_time.iloc[0])
        lo = close - T * 60
        a, tr, have = np.zeros(T), np.zeros(T), 0
        for tk in g.ticker:
            p = os.path.join(KH, "candles_1m", series, f"{tk}.json.gz")
            if not os.path.exists(p):
                continue
            have += 1
            for c in json.load(gzip.open(p, "rt"))["candlesticks"]:
                e = c["end_period_ts"]
                if lo < e <= close:
                    j = min(T - 1, (e - lo - 1) // 60)
                    a[j] += 1
                    if float(c.get("volume") or 0) > 0:
                        tr[j] += 1
        if have:
            out[day] = {"activity": a, "trades": tr, "contracts": have}
    return out


def fit_all(data, idx):
    """Fit every (series, count) on the days idx (a resample). Returns {key: (n, half_life)}."""
    return {k: (r["n"], r["half_life"]) for k, N in data.items() for r in [fit(N[idx])]}


_DATA = None


def _init(d):
    global _DATA
    _DATA = d


def _boot(seed):
    rng = np.random.default_rng(seed)
    D = next(iter(_DATA.values())).shape[0]
    return fit_all(_DATA, rng.integers(0, D, D))


def ci(x):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    return float(np.percentile(x, 2.5)), float(np.percentile(x, 97.5))


def dispersion(N, r):
    from microstructure.hawkes import excitation
    lam = r["baseline"][None, :] + r["n"] * excitation(N, r["phi"])
    lam = np.maximum(lam, 1e-9)
    return float(((N - lam) ** 2 / lam).sum() / N.size)        # ~1 if Poisson; parameters are few next to N.size


def main():
    os.makedirs(OUT, exist_ok=True)
    raw = {s: load(s) for s in SERIES}
    dates = sorted(set(raw["KXINX"]) & set(raw["KXNASDAQ100"]))
    lines = [f"Days: {len(dates)} common pre-holdout days, {dates[0]} to {dates[-1]} "
             f"(S&P alone {len(raw['KXINX'])}, Nasdaq alone {len(raw['KXNASDAQ100'])})."]
    data = {(s, c): np.array([raw[s][d][c] for d in dates]) for s in SERIES for c in COUNTS}
    for (s, c), N in data.items():
        ncon = np.mean([raw[s][d]["contracts"] for d in dates])
        lines.append(f"  {SERIES[s]:<10} {c:<8} mean count/min {N.mean():6.2f}   zero minutes {100 * (N == 0).mean():5.1f}%   "
                     f"first hour {N[:, :60].mean():6.2f}  last hour {N[:, -60:].mean():6.2f}   contracts/day {ncon:.0f}")
    if SMOKE:
        print("\n".join(lines))
        return

    D = len(dates)
    res = {}
    for (s, c), N in data.items():
        r = fit(N); rc = fit(N, K=1); r0 = fit(N, n0_only=True)
        late = fit(N[:, :T - 10])
        h1 = np.array([d < "2026-01-01" for d in dates])
        res[(s, c)] = {"n": r["n"], "half_life": r["half_life"], "n_constant_baseline": rc["n"],
                       "half_life_constant_baseline": rc["half_life"], "LR": 2 * (r["loglik"] - r0["loglik"]),
                       "dispersion": dispersion(N, r), "n_drop_last10": late["n"],
                       "n_oct_dec": fit(N[h1])["n"], "n_jan_mar": fit(N[~h1])["n"],
                       "baseline": r["baseline"].tolist(), "mean_by_minute": N.mean(0).tolist()}
        print(f"fitted {s} {c}: n = {r['n']:.3f}, half-life {r['half_life']:.2f}", flush=True)

    with ProcessPoolExecutor(initializer=_init, initargs=(data,)) as ex:
        boots = list(ex.map(_boot, range(N_BOOT), chunksize=8))

    lines.append(f"\nDecision rules (95% intervals, {N_BOOT} day-bootstrap resamples; self-excitation needs lower end > {LOWER}):")
    for (s, c), r in res.items():
        nb = [b[(s, c)][0] for b in boots]; hb = [b[(s, c)][1] for b in boots]
        lo, hi = ci(nb); hlo, hhi = ci(hb)
        r.update(n_ci=[lo, hi], half_life_ci=[hlo, hhi])
        v = "CONFIRMED" if lo > LOWER else "NO meaningful self-excitation" if hi < LOWER else "INCONCLUSIVE"
        if v == "CONFIRMED" and r["half_life"] > HALF_LIFE_CAP - 0.5:
            v = "slow, not separable from the baseline (half-life at the cap)"
        r["verdict"] = v
        lines.append(f"  {SERIES[s]:<10} {c:<8} n = {r['n']:.3f} ({lo:.3f} to {hi:.3f})   half-life {r['half_life']:.2f} min "
                     f"({hlo:.2f} to {hhi:.2f})   -> {v}")
    lines.append("\nS&P minus Nasdaq, paired by resampled date:")
    for c in COUNTS:
        diff = [b[("KXINX", c)][0] - b[("KXNASDAQ100", c)][0] for b in boots]
        point = res[("KXINX", c)]["n"] - res[("KXNASDAQ100", c)]["n"]
        lo, hi = ci(diff)
        lines.append(f"  {c:<8} {point:+.3f} ({lo:+.3f} to {hi:+.3f})   -> {'differ' if lo > 0 or hi < 0 else 'no detectable difference'}")
    lines.append("\nReported only (not part of any verdict):")
    for (s, c), r in res.items():
        lines.append(f"  {SERIES[s]:<10} {c:<8} constant baseline n = {r['n_constant_baseline']:.3f} (half-life "
                     f"{r['half_life_constant_baseline']:.1f})   LR vs n=0 {r['LR']:9.1f}   dispersion {r['dispersion']:.2f}   "
                     f"drop last 10 min n = {r['n_drop_last10']:.3f}   Oct-Dec {r['n_oct_dec']:.3f}   Jan-Mar {r['n_jan_mar']:.3f}")

    txt = "\n".join(lines)
    print(txt)
    open(os.path.join(OUT, "summary.txt"), "w").write(txt + "\n")
    json.dump({f"{s}|{c}": r for (s, c), r in res.items()} | {"dates": dates, "n_boot": N_BOOT},
              open(os.path.join(OUT, "results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
