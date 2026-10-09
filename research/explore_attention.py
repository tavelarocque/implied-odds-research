"""Layer 9, EXPLORATORY: is Kalshi's long-shot overpricing larger after high-attention days?

Development sample only (Kalshi quotes before FINAL_TEST_START, as saved by research/calibration.py). This script
looks for a hypothesis; it tests nothing. What it finds is written into research/PREREGISTRATION_LAYER9.md, and the
test runs on the live forward window, never on this sample.

Attention on trading day t = log of the previous UTC day's Wikipedia views over the median of the 28 days before that.
The previous day, because a UTC day runs past the 4pm ET close, so day t's own views partly react to day t's move.

Run from the project root (after collect/attention_history.py and research/calibration.py [SERIES]):
    python3 research/explore_attention.py [KXINX|KXNASDAQ100]
"""
import os, sys
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERIES = sys.argv[1] if len(sys.argv) > 1 else "KXINX"
QUOTES = os.path.join(ROOT, "research", "output", "calibration" if SERIES == "KXINX" else f"calibration_{SERIES}", "quotes.csv.gz")
WIKI = os.path.join(ROOT, "data", "history", "attention", "wikipedia_daily.csv")
OWN = {"KXINX": "S&P_500", "KXNASDAQ100": "Nasdaq-100"}[SERIES]
rng = np.random.default_rng(9)


def abnormal(views):
    """log(views on day t-1 / median of days t-29..t-2), indexed by day t."""
    v = views.sort_index().asfreq("D")
    base = v.shift(2).rolling(28, min_periods=20).median()
    return np.log(v.shift(1) / base)


def boot_diff(df, flag, col, n=2000):
    """95% interval for mean(col | flag) - mean(col | not flag), resampling whole days (per-day sums, so fast)."""
    g = df.groupby("date").apply(lambda x: pd.Series({"s1": x.loc[x[flag], col].sum(), "n1": x[flag].sum(),
                                                       "s0": x.loc[~x[flag], col].sum(), "n0": (~x[flag]).sum()}))
    a = g.values
    w = rng.multinomial(len(a), np.full(len(a), 1 / len(a)), size=n)        # how often each day is drawn
    t = w @ a
    with np.errstate(invalid="ignore", divide="ignore"):
        d = t[:, 0] / t[:, 1] - t[:, 2] / t[:, 3]
    return np.nanpercentile(d, [2.5, 97.5])


def main():
    q = pd.read_csv(QUOTES)
    w = pd.read_csv(WIKI, parse_dates=["date"]).pivot(index="date", columns="article", values="views")
    att = pd.DataFrame({a: abnormal(w[a]) for a in w.columns})
    q["d"] = pd.to_datetime(q.date)
    q = q.join(att, on="d")
    q["over"] = q.mid - q.y                       # positive = the contract was priced above how often it paid
    print(f"{SERIES}: {len(q):,} quotes on {q.date.nunique()} days, {q.date.min()} to {q.date.max()} (development sample)")
    for meas in (OWN, "Stock_market_crash", "Recession", "Stock_market"):
        if meas not in q:
            continue
        cut = att[meas].dropna()
        thr = cut.quantile(0.8)
        q["hi"] = q[meas] > thr
        print(f"\nAttention = {meas} (previous day, top fifth = abnormal views above {thr:+.2f} log points):")
        for h in (1, 3, 6):
            for name, sel in (("long shots (mid <= 10c)", q.mid <= 0.10), ("all quotes", q.mid > -1)):
                s = q[(q.h == h) & sel & q[meas].notna()]
                if s.hi.sum() < 20:
                    continue
                a, b = s[s.hi].over.mean(), s[~s.hi].over.mean()
                lo, hi = boot_diff(s, "hi", "over")
                print(f"  {h}h  {name:<24} overpricing high-attention {100 * a:+.2f}c (n {s.hi.sum()}, "
                      f"{s[s.hi].date.nunique()} days) vs other {100 * b:+.2f}c; difference {100 * (a - b):+.2f}c "
                      f"({100 * lo:+.2f} to {100 * hi:+.2f})")


if __name__ == "__main__":
    main()
