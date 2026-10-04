# %% [markdown]
# # Layer 3: who leads price discovery, Kalshi or Polymarket?
#
# Pre-registered in research/PREREGISTRATION_LAYER3.md (committed before any minute-level result). When the two
# venues disagree about "will the index close above yesterday's close?", which one moves to meet the other?
#
#   dK(t) = aK + bK * gap(t - 10min) + e,   dP(t) = aP + bP * gap(t - 10min) + e,   gap = P_poly - P_kalshi
#
# bK > 0: Kalshi moves toward Polymarket. bP < 0: Polymarket moves toward Kalshi. Kalshi's share of the adjustment
# s = bK / (bK - bP); above 0.5 means Kalshi does most of the moving, i.e. Polymarket leads.
# The gap is lagged one interval so quote noise (which reverses mechanically) can't fake a follower.
#
# Run from the project root:  python3 research/price_discovery.py [spx|ndx]

# %%
import gzip, json, os, re, sys
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
from implied import make_ladder, prob_above
from config import exploratory, FINAL_TEST_START

K_HIST = os.path.join(ROOT, "data", "history", "kalshi")
P_HIST = os.path.join(ROOT, "data", "history", "polymarket")
INDEX = sys.argv[1] if len(sys.argv) > 1 else "spx"
SERIES, POLY_KIND, NAME = {"spx": ("KXINX", "close", "S&P 500"), "ndx": ("KXNASDAQ100", "ndx_close", "Nasdaq-100")}[INDEX]
OUT = os.path.join(ROOT, "research", "output", f"price_discovery_{INDEX}")
os.makedirs(OUT, exist_ok=True)
GRID_MIN = list(range(360, 19, -10))          # minutes before the close: 360, 350, ..., 20
POLY_MAX_AGE = 600                            # a Polymarket price older than 10 minutes counts as missing
BOOT, PERMS = 2000, 1000
rng = np.random.default_rng(3)


def read_jsonl(p):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return [json.loads(l) for l in f]


def ts(iso):
    return int(datetime.fromisoformat(re.sub(r"\.\d+", "", iso.replace("Z", "+00:00"))).timestamp())


def money(x):
    return None if x in (None, "") else float(str(x).replace(",", ""))


def dollars(block, field):
    if not block:
        return np.nan
    raw = block.get(f"{field}_dollars", block.get(field))
    if raw in (None, ""):
        return np.nan
    return float(raw) / 100 if not isinstance(raw, str) else float(raw)


# %% Day matching, identical to research/cross_venue.py
mk = pd.DataFrame(read_jsonl(os.path.join(K_HIST, f"markets_{SERIES}.jsonl.gz")))
mk = mk[mk.result.isin(["yes", "no"])]
mk["day"] = mk.close_time.str[:10]
days = mk.groupby("day").agg(event=("event_ticker", "first"), close_time=("close_time", "first"),
                             settle=("expiration_value", lambda s: next((money(v) for v in s if v), None))).sort_index()
days["prev_close"] = days.settle.shift(1)
days["prev_day"] = pd.Series(days.index, index=days.index).shift(1)
days.loc[((pd.to_datetime(days.index) - pd.to_datetime(days.prev_day)).dt.days > 4).values, "prev_close"] = np.nan

pm = pd.DataFrame(read_jsonl(os.path.join(P_HIST, "events.jsonl.gz")))
pm = pm[(pm.kind == POLY_KIND) & pm.rules.str.contains("prior trading day", case=False, na=False)]
pm = pm[exploratory(pm.date)]


def poly_up(slug):
    p = os.path.join(P_HIST, "prices_10m", f"{slug}.json.gz")
    if not os.path.exists(p):
        return None
    with gzip.open(p, "rt", encoding="utf-8") as f:
        up = json.load(f)["history"].get("Up", [])
    return (np.array([x["t"] for x in up]), np.array([x["p"] for x in up])) if up else None


def quote_at(c, target, side):
    """Yes bid/ask of a contract at `target`: its last 1-minute candle at or before then (Kalshi writes a candle
    only when something changes), or, before its first candle, that candle's opening quote."""
    if c is None:
        return np.nan
    t, cs = c
    i = np.searchsorted(t, target, side="right") - 1
    return dollars(cs[i].get(f"yes_{side}"), "close") if i >= 0 else dollars(cs[0].get(f"yes_{side}"), "open")


# %% Build the 10-minute panel: one row per day x grid time
cdir = os.path.join(K_HIST, "candles_1m", SERIES)
rows, missing_files = [], 0
for e in pm.itertuples():
    if e.date not in days.index or pd.isna(days.loc[e.date, "prev_close"]):
        continue
    d = days.loc[e.date]
    pu = poly_up(e.slug)
    if pu is None:
        continue
    lad_ms = mk[mk.event_ticker == d.event]
    candles = {}
    for m in lad_ms.itertuples():
        p = os.path.join(cdir, f"{m.ticker}.json.gz")
        if not os.path.exists(p):
            missing_files += 1
            continue
        with gzip.open(p, "rt", encoding="utf-8") as f:
            cs = json.load(f)["candlesticks"]
        candles[m.ticker] = (np.array([c["end_period_ts"] for c in cs]), cs) if cs else None
    close_ts = ts(d.close_time)
    for mins in GRID_MIN:
        target = close_ts - mins * 60
        q = []
        for m in lad_ms.itertuples():
            c = candles.get(m.ticker)
            bid, ask = quote_at(c, target, "bid"), quote_at(c, target, "ask")
            q.append({"strike_type": m.strike_type, "floor_strike": m.floor_strike, "cap_strike": m.cap_strike,
                      "bid": 0.0 if not bid == bid else bid,               # no quote recorded: nobody bidding
                      "ask": ask if ask == ask and 0 < ask < 1 else np.nan})
        lad = make_ladder(q)
        i = np.searchsorted(pu[0], target, side="right") - 1
        p_poly = pu[1][i] if i >= 0 and target - pu[0][i] <= POLY_MAX_AGE else np.nan
        rows.append({"date": e.date, "mins": mins, "p_poly": p_poly,
                     "p_k": prob_above(lad, d.prev_close, "bid"), "p_k_mid": prob_above(lad, d.prev_close, "mid")})

panel = pd.DataFrame(rows).sort_values(["date", "mins"], ascending=[True, False]).reset_index(drop=True)
print(f"{NAME}: {panel.date.nunique()} days, {len(panel):,} 10-minute points ({FINAL_TEST_START} on reserved); "
      f"1-minute candle files missing for {missing_files} contracts")
if os.environ.get("SMOKE") == "1":                 # data-quality check only; prints no result
    print(f"Polymarket price present: {panel.p_poly.notna().mean():.0%}; Kalshi probability present: "
          f"{panel.p_k.notna().mean():.0%}; both: {(panel.p_poly.notna() & panel.p_k.notna()).mean():.0%}")
    print(f"Kalshi probability changes between consecutive points: "
          f"{(panel.groupby('date').p_k.diff().abs() > 1e-9).mean():.0%} of points")
    sys.exit(0)


def add_changes(df, kcol):
    g = df.groupby("date")
    out = df.copy()
    out["gap"] = out.p_poly - out[kcol]
    out["gap_lag"] = g["p_poly"].shift(1) - g[kcol].shift(1)       # the previous grid point (10 minutes earlier)
    out["dK"] = g[kcol].shift(-1) - out[kcol]
    out["dP"] = g["p_poly"].shift(-1) - out.p_poly
    return out


def slopes(df, x):
    """OLS slopes of dK and dP on x, by per-day sufficient statistics (fast bootstrap and permutation)."""
    d = df.dropna(subset=[x, "dK", "dP"])
    s = d.groupby("date").agg(n=(x, "size"), sx=(x, "sum"), sxx=(x, lambda v: (v * v).sum()),
                              sk=("dK", "sum"), sp=("dP", "sum"),
                              sxk=("dK", lambda v: (v * d.loc[v.index, x]).sum()),
                              sxp=("dP", lambda v: (v * d.loc[v.index, x]).sum()))
    return s


def fit(S, w=None):
    w = np.ones(len(S)) if w is None else w
    n, sx, sxx = (S.n * w).sum(), (S.sx * w).sum(), (S.sxx * w).sum()
    vx = sxx - sx * sx / n
    bK = ((S.sxk * w).sum() - sx * (S.sk * w).sum() / n) / vx
    bP = ((S.sxp * w).sum() - sx * (S.sp * w).sum() / n) / vx
    return bK, bP


def analyse(df, x, label, perms=0):
    S = slopes(df, x)
    bK, bP = fit(S)
    boot = []
    for _ in range(BOOT):
        w = np.bincount(rng.integers(0, len(S), len(S)), minlength=len(S))
        boot.append(fit(S, w))
    boot = np.array(boot)
    diff, share = boot[:, 0] - boot[:, 1], boot[:, 0] / (boot[:, 0] - boot[:, 1])
    r = {"label": label, "days": len(S), "obs": int(S.n.sum()), "bK": bK, "bP": bP, "diff": bK - bP,
         "diff_lo": np.percentile(diff, 2.5), "diff_hi": np.percentile(diff, 97.5), "share_kalshi": bK / (bK - bP),
         "share_lo": np.percentile(share, 2.5), "share_hi": np.percentile(share, 97.5)}
    if perms:
        # Masters: pair each day's lagged gaps with another day's changes (same grid positions).
        d = df.dropna(subset=[x, "dK", "dP"])
        dates = d.date.unique()
        by_day = {k: v for k, v in d.groupby("date")}
        full = df.set_index(["date", "mins"])
        null = []
        for _ in range(perms):
            perm = dict(zip(dates, rng.permutation(dates)))
            xs, ks, ps = [], [], []
            for a, g in by_day.items():
                other = full.loc[perm[a]].reindex(g.mins.values)
                ok = other.dK.notna().values & other.dP.notna().values
                xs.append(g[x].values[ok]); ks.append(other.dK.values[ok]); ps.append(other.dP.values[ok])
            X, Kc, Pc = np.concatenate(xs), np.concatenate(ks), np.concatenate(ps)
            Xc = X - X.mean()
            null.append((Xc @ Kc - Xc @ Pc) / (Xc @ Xc))
        r["perm_p"] = (1 + np.sum(np.array(null) >= bK - bP)) / (1 + perms)
    return r


def verdict(r):
    if not r["diff_lo"] > 0:
        return "the gap does not close at a 10-minute horizon"
    if r.get("perm_p", 0) >= 0.01:
        return "gap closing not confirmed by the permutation test (p >= 0.01)"
    if r["share_lo"] > 0.5:
        return "POLYMARKET LEADS (Kalshi does most of the moving)"
    if r["share_hi"] < 0.5:
        return "KALSHI LEADS (Polymarket does most of the moving)"
    return "no detectable leader"


# %% Primary (pre-registered): bids-only Kalshi, lagged gap, with the permutation check
P = add_changes(panel, "p_k")
prim = analyse(P, "gap_lag", "PRIMARY: bids-only, lagged gap", perms=PERMS)
print(f"\nPRIMARY ({NAME}, {prim['days']} days, {prim['obs']:,} observations)")
print(f"  bK = {prim['bK']:+.3f} (Kalshi moves toward Polymarket),  bP = {prim['bP']:+.3f} (Polymarket moves toward Kalshi)")
print(f"  rule 1, gap closes: bK - bP = {prim['diff']:.3f}  [{prim['diff_lo']:.3f}, {prim['diff_hi']:.3f}]; "
      f"permutation p = {prim['perm_p']:.3f}")
print(f"  rule 2, Kalshi's share of the adjustment: {prim['share_kalshi']:.2f}  [{prim['share_lo']:.2f}, {prim['share_hi']:.2f}]")
print(f"  VERDICT: {verdict(prim)}")

# %% Secondary, reported but not part of any verdict
sec = [prim,
       analyse(P, "gap", "unlagged gap (noise not corrected)"),
       analyse(add_changes(panel, "p_k_mid"), "gap_lag", "mid-based Kalshi, lagged gap")]
for lo, hi in ((240, 360), (120, 240), (20, 120)):
    sub = P[(P.mins > lo) & (P.mins <= hi)] if lo else P[P.mins <= hi]
    sec.append(analyse(sub, "gap_lag", f"{hi // 60}-{lo // 60} hours before the close"))
tab = pd.DataFrame(sec)
print("\nAll specifications (share > 0.5 = Polymarket leads):")
print(tab[["label", "obs", "bK", "bP", "share_kalshi", "share_lo", "share_hi"]].to_string(index=False, float_format=lambda v: f"{v:.3f}"))

xc = []
for lag in range(-3, 4):                       # positive lag: Kalshi's change follows Polymarket's
    a = P.groupby("date").apply(lambda g: pd.DataFrame({"p": g.dP.values, "k": g.dK.shift(-lag).values}), include_groups=False)
    a = a.dropna()
    xc.append({"lag_min": 10 * lag, "corr": np.corrcoef(a.p, a.k)[0, 1]})
xc = pd.DataFrame(xc)
print("\nCorrelation of Polymarket's 10-minute change with Kalshi's change `lag` minutes later:")
print(xc.to_string(index=False, float_format=lambda v: f"{v:.3f}"))

tab.to_csv(os.path.join(OUT, "results.csv"), index=False)
xc.to_csv(os.path.join(OUT, "cross_correlation.csv"), index=False)
panel.to_csv(os.path.join(OUT, "panel.csv.gz"), index=False)

fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
ax = axes[0]
ax.bar(xc.lag_min, xc["corr"], width=7, color=["#4a6fa5" if l < 0 else "#b8520a" if l > 0 else "#777" for l in xc.lag_min])
ax.set_xlabel("Lag (minutes): positive = Kalshi moves after Polymarket"); ax.set_ylabel("Correlation of 10-minute changes")
ax.set_title(f"{NAME}: lead-lag between venues"); ax.axhline(0, color="#999", lw=1)
ax = axes[1]
b = tab.iloc[3:]
ax.errorbar(range(len(b)), b.share_kalshi, yerr=[b.share_kalshi - b.share_lo, b.share_hi - b.share_kalshi], fmt="o", color="#b8520a")
ax.axhline(0.5, color="#999", ls="--", lw=1)
ax.set_xticks(range(len(b))); ax.set_xticklabels(b.label, fontsize=8)
ax.set_ylabel("Kalshi's share of the adjustment"); ax.set_title("Above 0.5: Polymarket leads")
fig.tight_layout(); fig.savefig(os.path.join(OUT, "price_discovery.png"), dpi=150)
print(f"\nWritten to {OUT}")
