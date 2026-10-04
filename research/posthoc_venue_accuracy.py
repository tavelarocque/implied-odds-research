"""POST HOC (added after the Nasdaq replication results were seen; not part of the pre-registration).

The replication's second failure: with the bids-only estimator, Kalshi's Nasdaq-100 ladder was significantly more
accurate than Polymarket's Nasdaq up/down market at two horizons, while on the S&P 500 the venues were tied.
Hypothesis: Polymarket's Nasdaq market is much thinner than its S&P market, so its price is staler and noisier.

Checks, all on the pre-holdout period:
  1. Polymarket volume per daily market, S&P vs Nasdaq.
  2. How often Polymarket's price actually moves in the last 6 hours (share of 10-minute steps with a change).
  3. Brier score by venue for both indices (bids-only Kalshi).
  4. Within each index: is Polymarket's accuracy gap bigger on its low-volume days?

Run from the project root:  python3 research/posthoc_venue_accuracy.py
"""
import gzip, json, os, sys
from datetime import datetime

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import FINAL_TEST_START

PM = os.path.join(ROOT, "data", "history", "polymarket")
rng = np.random.default_rng(11)
IDX = {"S&P 500": ("close", "cross_venue"), "Nasdaq-100": ("ndx_close", "cross_venue_ndx")}

with gzip.open(os.path.join(PM, "events.jsonl.gz"), "rt", encoding="utf-8") as f:
    ev = pd.DataFrame([json.loads(l) for l in f])
ev["volume"] = pd.to_numeric(ev.volume, errors="coerce")
ev = ev[(ev.date >= "2025-10-16") & (ev.date < FINAL_TEST_START)]


def activity(slug, end_iso):
    p = os.path.join(PM, "prices_10m", f"{slug}.json.gz")
    if not os.path.exists(p):
        return np.nan
    with gzip.open(p, "rt", encoding="utf-8") as f:
        hist = json.load(f)["history"].get("Up", [])
    end = datetime.fromisoformat(end_iso.replace("Z", "+00:00")).timestamp()
    px = [h["p"] for h in hist if end - 6 * 3600 <= h["t"] <= end]
    if len(px) < 6:
        return np.nan
    return float(np.mean(np.diff(px) != 0))


def boot_ci(df, col, n=2000):
    days = df.date.unique()
    g = df.groupby("date")[col].agg(["sum", "count"]).reindex(days)
    out = []
    for _ in range(n):
        s = g.iloc[rng.integers(0, len(days), len(days))]
        out.append(s["sum"].sum() / s["count"].sum())
    return np.percentile(out, [2.5, 97.5])


rows = []
for name, (kind, outdir) in IDX.items():
    e = ev[ev.kind == kind].copy()
    e["moves"] = [activity(s, t) for s, t in zip(e.slug, e.end)]
    cv = pd.read_csv(os.path.join(ROOT, "research", "output", outdir, "cross_venue.csv"))
    cv = cv[cv.date < FINAL_TEST_START].copy()
    cv["b_k"] = (cv.p_kalshi_bid - cv.up) ** 2
    cv["b_p"] = (cv.p_poly - cv.up) ** 2
    cv["diff"] = cv.b_k - cv.b_p                       # below zero = Kalshi more accurate
    cv = cv.merge(e[["date", "volume"]], on="date", how="left")
    med = e.volume.median()
    lo_v, hi_v = cv[cv.volume < med], cv[cv.volume >= med]
    rows.append({
        "index": name, "markets": len(e),
        "median_volume_$": med, "mean_volume_$": e.volume.mean(),
        "price_moves_share": e.moves.mean(),
        "brier_kalshi_bid": cv.b_k.mean(), "brier_poly": cv.b_p.mean(),
        "diff_all": cv["diff"].mean(), "diff_all_ci": boot_ci(cv, "diff"),
        "diff_low_vol": lo_v["diff"].mean(), "diff_low_ci": boot_ci(lo_v, "diff"),
        "diff_high_vol": hi_v["diff"].mean(), "diff_high_ci": boot_ci(hi_v, "diff"),
    })

print("POST HOC: why was Kalshi more accurate than Polymarket on the Nasdaq-100? (pre-holdout data)\n")
for r in rows:
    print(f"{r['index']}: {r['markets']} Polymarket daily markets")
    print(f"  volume per market: median ${r['median_volume_$']:,.0f}, mean ${r['mean_volume_$']:,.0f}")
    print(f"  Polymarket price changed on {100 * r['price_moves_share']:.0f}% of 10-minute steps in the last 6 hours")
    print(f"  Brier (all horizons): Kalshi bids-only {r['brier_kalshi_bid']:.4f}, Polymarket {r['brier_poly']:.4f}")
    for lab, k in (("all days", "all"), ("Polymarket low-volume days", "low"), ("Polymarket high-volume days", "high")):
        ci = r[f"diff_{k}_ci"]
        m = r["diff_low_vol"] if k == "low" else r["diff_high_vol"] if k == "high" else r["diff_all"]
        print(f"  Brier(Kalshi) - Brier(Polymarket), {lab:28}: {m:+.4f}  [{ci[0]:+.4f}, {ci[1]:+.4f}]")
    print()
out = os.path.join(ROOT, "research", "output", "posthoc_venue_accuracy")
os.makedirs(out, exist_ok=True)
pd.DataFrame(rows).to_csv(os.path.join(out, "summary.csv"), index=False)
