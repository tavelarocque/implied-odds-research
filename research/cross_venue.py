# %% [markdown]
# # Layer 6: Kalshi vs Polymarket on the same question
#
# Polymarket's "SPX up or down on <date>" pays if the S&P 500 closes above the previous day's close (for every
# market from 2025-10-16; the first market, 2025-10-15, compared with the same day's open and is excluded).
# Kalshi had no single up/down contract in this period, so its probability of the same event is built from its
# daily range ladder (KXINX). Both venues settle on the official S&P 500 close.
#
# Three questions:
#   1. How far apart are the two venues' probabilities, and does the gap shrink toward the close?
#   2. Which venue forecast the outcome better (Brier score)?
#   3. Was there ever a riskless arbitrage after costs? Buying Polymarket "Down" plus every Kalshi range that
#      pays when the close is above K (including the range containing K) pays at least $1 in every outcome,
#      so if that package costs less than $1, it's free money. Same for the mirror trade.
#
# Run from the project root:  python3 research/cross_venue.py [spx|ndx]   (default spx)

# %%
import glob, gzip, json, os, re, sys
from datetime import datetime
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
from implied import make_ladder, prob_above, basket_cost
from implied.kalshi_ladder import ladder_mids


def ladder_mids_tail(lad, K, far=100):
    """Share of the mid-based distribution sitting in ranges more than `far` points from K that nobody bids on."""
    w = ladder_mids(lad, "mid")
    centre = np.where(np.isfinite(lad.lo) & np.isfinite(lad.hi), (lad.lo + lad.hi) / 2, np.where(np.isfinite(lad.lo), lad.lo, lad.hi))
    return w[(np.abs(centre - K) > far) & (lad.bid.fillna(0) == 0)].sum()
from config import exploratory, FINAL_TEST_START, HOLDOUT_UNLOCKED

K_HIST = os.path.join(ROOT, "data", "history", "kalshi")
P_HIST = os.path.join(ROOT, "data", "history", "polymarket")
INDEX = sys.argv[1] if len(sys.argv) > 1 else "spx"       # "spx" or "ndx"
SERIES, POLY_KIND, INDEX_NAME = {"spx": ("KXINX", "close", "S&P 500"), "ndx": ("KXNASDAQ100", "ndx_close", "Nasdaq-100")}[INDEX]
OUT = os.path.join(ROOT, "research", "output", "cross_venue" if INDEX == "spx" else f"cross_venue_{INDEX}")
os.makedirs(OUT, exist_ok=True)
HOURS = [6, 5, 4, 3, 2, 1]            # hours before the 4pm ET close
POLY_HALF_SPREAD = 0.005              # assumed cost of crossing Polymarket's spread (its history has no bid/ask)
POLY_FEE = 0.0                        # assumed Polymarket taker fee on these markets
STALE_S = 3600


def read_jsonl(p):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return [json.loads(l) for l in f]


def ts(iso):
    return int(datetime.fromisoformat(re.sub(r"\.\d+", "", iso.replace("Z", "+00:00"))).timestamp())


def money(x):
    return None if x in (None, "") else float(str(x).replace(",", ""))


def dollars(block, field="close"):
    if not block:
        return np.nan
    raw = block.get(f"{field}_dollars")
    if raw in (None, ""):
        raw = block.get(field)
        if raw in (None, ""):
            return np.nan
        if not isinstance(raw, str):
            return float(raw) / 100
    return float(raw)

# %% Kalshi: settled ladders by trading day, with the close (settlement value) of each day
mk = pd.DataFrame(read_jsonl(os.path.join(K_HIST, f"markets_{SERIES}.jsonl.gz")))
mk = mk[mk.result.isin(["yes", "no"])]
mk["day"] = mk.close_time.str[:10]
days = mk.groupby("day").agg(event=("event_ticker", "first"), close_time=("close_time", "first"),
                             settle=("expiration_value", lambda s: next((money(v) for v in s if v), None))).sort_index()
days["prev_close"] = days.settle.shift(1)
days["prev_day"] = pd.Series(days.index, index=days.index).shift(1)
gap_days = (pd.to_datetime(days.index) - pd.to_datetime(days.prev_day)).dt.days
days.loc[gap_days.values > 4, "prev_close"] = np.nan          # don't bridge long gaps in the data

# %% Polymarket: daily close markets, their rule, outcome and 10-minute price history
pm = pd.DataFrame(read_jsonl(os.path.join(P_HIST, "events.jsonl.gz")))
allk = pm[pm.kind == POLY_KIND]
pm = allk[allk.rules.str.contains("prior trading day", case=False, na=False)].copy()
print(f"Polymarket {INDEX_NAME} daily markets: {len(allk)}; settling on close vs previous close: {len(pm)} "
      f"({pm.date.min()} to {pm.date.max()}); other rules excluded: {len(allk) - len(pm)}")
pm = pm[exploratory(pm.date)]
print(f"after holdout: {len(pm)}" + ("" if HOLDOUT_UNLOCKED else f" (from {FINAL_TEST_START} reserved)"))


def poly_series(slug):
    p = os.path.join(P_HIST, "prices_10m", f"{slug}.json.gz")
    if not os.path.exists(p):
        return None
    with gzip.open(p, "rt", encoding="utf-8") as f:
        h = json.load(f)["history"]
    up, down = h.get("Up", []), h.get("Down", [])
    if not up:
        return None
    return (np.array([x["t"] for x in up]), np.array([x["p"] for x in up]),
            np.array([x["t"] for x in down]) if down else None, np.array([x["p"] for x in down]) if down else None)


def at(t_arr, v_arr, target, max_age):
    i = np.searchsorted(t_arr, target, side="right") - 1
    return v_arr[i] if i >= 0 and target - t_arr[i] <= max_age else np.nan

# %% Line the two venues up hour by hour
cdir = os.path.join(K_HIST, "candles_60m", SERIES)
rows, agree, n_checked, skipped = [], 0, 0, 0
for e in pm.itertuples():
    if e.date not in days.index or pd.isna(days.loc[e.date, "prev_close"]):
        skipped += 1
        continue
    d = days.loc[e.date]
    K, close = d.prev_close, d.settle
    poly_up_won = json.loads(e.outcome_prices)[0] == "1" if e.outcome_prices else None
    up = 1.0 if close > K else 0.0 if close < K else 0.5
    if poly_up_won is not None and up != 0.5:
        n_checked += 1
        agree += (poly_up_won == bool(up))
    ps = poly_series(e.slug)
    if ps is None:
        skipped += 1
        continue
    ladder_ms = mk[mk.event_ticker == d.event]
    candles = {}
    for m in ladder_ms.itertuples():
        p = os.path.join(cdir, f"{m.ticker}.json.gz")
        if os.path.exists(p):
            with gzip.open(p, "rt", encoding="utf-8") as f:
                cs = json.load(f)["candlesticks"]
            candles[m.ticker] = (np.array([c["end_period_ts"] for c in cs]), cs)
    close_ts = ts(d.close_time)
    for h in HOURS:
        target = close_ts - h * 3600
        q = []
        for m in ladder_ms.itertuples():
            bid = ask = np.nan
            if m.ticker in candles:
                tt, cs = candles[m.ticker]
                i = np.searchsorted(tt, target, side="right") - 1
                if i >= 0 and target - tt[i] <= STALE_S:
                    bid, ask = dollars(cs[i].get("yes_bid")), dollars(cs[i].get("yes_ask"))
            q.append({"strike_type": m.strike_type, "floor_strike": m.floor_strike, "cap_strike": m.cap_strike,
                      "bid": bid if bid == bid else 0.0, "ask": ask if ask == ask and ask > 0 else np.nan})
        lad = make_ladder(q)
        quoted = lad.ask.notna().mean()
        raw_sum = ((lad.bid + lad.ask) / 2).sum()
        p_up_poly = at(ps[0], ps[1], target, 1800)
        p_down_poly = at(ps[2], ps[3], target, 1800) if ps[2] is not None else 1 - p_up_poly
        if quoted < 0.9 or not (0.8 < raw_sum < 1.6) or np.isnan(p_up_poly):
            continue
        cost_up_k, n_up = basket_cost(lad, K, "up")
        cost_dn_k, n_dn = basket_cost(lad, K, "down")
        cost_up_k1, _ = basket_cost(lad, K, "up", contracts=1)
        cost_dn_k1, _ = basket_cost(lad, K, "down", contracts=1)
        poly_extra = POLY_HALF_SPREAD + POLY_FEE
        rows.append({
            "date": e.date, "h": h, "K": K, "up": up,
            "p_kalshi": prob_above(lad, K), "p_kalshi_bid": prob_above(lad, K, "bid"), "p_poly": p_up_poly,
            # Trade A: Kalshi up basket + Polymarket Down.  Trade B: Kalshi down basket + Polymarket Up.
            "cost_A": cost_up_k + p_down_poly + poly_extra, "cost_B": cost_dn_k + p_up_poly + poly_extra,
            "cost_A_1lot": cost_up_k1 + p_down_poly + poly_extra, "cost_B_1lot": cost_dn_k1 + p_up_poly + poly_extra,
            "gross_A": lad[lad.hi > K].ask.sum() + p_down_poly, "gross_B": lad[lad.lo < K].ask.sum() + p_up_poly,
            "n_basket": max(n_up, n_dn), "kalshi_raw_sum": raw_sum,
            "tail_mass": float(ladder_mids_tail(lad, K)),
        })

df = pd.DataFrame(rows)
print(f"settlement check: Polymarket's recorded outcome matches the outcome computed from Kalshi's settlement values "
      f"on {agree} of {n_checked} days")
if df.empty:
    sys.exit("No overlapping observations: pull Polymarket prices (collect/polymarket_history.py prices).")
df["gap"] = df.p_poly - df.p_kalshi
df["gap_bid"] = df.p_poly - df.p_kalshi_bid
df["best_cost"] = df[["cost_A", "cost_B"]].min(axis=1)
df["best_gross"] = df[["gross_A", "gross_B"]].min(axis=1)
df.to_csv(os.path.join(OUT, "cross_venue.csv"), index=False)
print(f"{len(df):,} matched observations over {df.date.nunique()} trading days ({df.date.min()} to {df.date.max()})")

# %% 1. How far apart, and does the gap shrink toward the close?
summary = df.groupby("h").apply(lambda g: pd.Series({
    "obs": len(g), "mean_gap_pp": 100 * g.gap.mean(), "mean_abs_gap_pp": 100 * g.gap.abs().mean(),
    "p90_abs_gap_pp": 100 * g.gap.abs().quantile(.9), "corr": np.corrcoef(g.p_kalshi, g.p_poly)[0, 1],
    "brier_kalshi": np.mean((g.p_kalshi - g.up) ** 2), "brier_poly": np.mean((g.p_poly - g.up) ** 2),
    "brier_average": np.mean(((g.p_kalshi + g.p_poly) / 2 - g.up) ** 2),
    "abs_gap_bid_pp": 100 * g.gap_bid.abs().mean(), "brier_kalshi_bid": np.nanmean((g.p_kalshi_bid - g.up) ** 2),
    "phantom_tail_pct": 100 * g.tail_mass.mean()})).sort_index(ascending=False)
print("\nBy hours before the close (gap = Polymarket minus Kalshi, in percentage points; *_bid = Kalshi from bids only):")
print(summary.to_string(float_format=lambda x: f"{x:.3f}"))

# %% 2. Which venue forecast better, with a day-level bootstrap on the Brier difference
rng = np.random.default_rng(3)
for est in ("p_kalshi", "p_kalshi_bid"):
  print(f" Kalshi estimator: {'bid-ask midpoints' if est == 'p_kalshi' else 'bids only'}")
  for h, g in df.groupby("h"):
    g = g[g[est].notna()]
    dk = (g[est] - g.up) ** 2 - (g.p_poly - g.up) ** 2
    codes, uniq = pd.factorize(g.date)
    by_day = np.bincount(codes, weights=dk.values) / np.bincount(codes)
    boots = [by_day[rng.integers(0, len(uniq), len(uniq))].mean() for _ in range(2000)]
    lo, hi = np.percentile(boots, [2.5, 97.5])
    verdict = "Polymarket better" if lo > 0 else "Kalshi better" if hi < 0 else "no significant difference"
    print(f"  {h}h: Brier(Kalshi) - Brier(Polymarket) = {by_day.mean():+.4f}  [{lo:+.4f}, {hi:+.4f}]  -> {verdict}")

# %% 3. Riskless arbitrage after costs
print(f"\nArbitrage packages pay at least $1 in every outcome. Median Kalshi basket size: {df.n_basket.median():.0f} contracts.")
print(f"  apparent (Kalshi asks, Polymarket price, no fees): cost < $1 in {100 * (df.best_gross < 1).mean():.1f}% of observations, "
      f"median {df.best_gross.median():.3f}")
print(f"  after Kalshi fees (large orders) and Polymarket spread: cost < $1 in {100 * (df.best_cost < 1).mean():.1f}%, "
      f"median {df.best_cost.median():.3f}, cheapest {df.best_cost.min():.3f}")
one_lot = df[["cost_A_1lot", "cost_B_1lot"]].min(axis=1)
print(f"  one contract of each (Kalshi rounds each fee up to a cent): cost < $1 in {100 * (one_lot < 1).mean():.1f}%, median {one_lot.median():.3f}")
hits = df[df.best_cost < 1].sort_values("best_cost")
if len(hits):
    print("\n  cheapest packages found:")
    print(hits[["date", "h", "p_kalshi", "p_poly", "best_gross", "best_cost", "n_basket"]].head(8).to_string(index=False, float_format=lambda x: f"{x:.3f}"))

# %% Figures
fig, axes = plt.subplots(1, 3, figsize=(15.5, 4.6))
ax = axes[0]
for h, c in [(6, "#9db4d6"), (3, "#4a6fa5"), (1, "#b8520a")]:
    g = df[df.h == h]
    ax.scatter(g.p_kalshi_bid, g.p_poly, s=10, alpha=.6, color=c, label=f"{h}h before close")
ax.plot([0, 1], [0, 1], color="#999", lw=1, ls="--")
ax.set_xlabel("Kalshi P(up), from bids on its range ladder"); ax.set_ylabel("Polymarket P(up)")
ax.set_title("The two venues agree closely"); ax.legend(frameon=False, fontsize=8)
ax = axes[1]
ax.plot(summary.index, summary.abs_gap_bid_pp, "o-", color="#4a6fa5", label="Kalshi from bids (main estimate)")
ax.plot(summary.index, summary.mean_abs_gap_pp, "o--", color="#bbb", label="Kalshi from midpoints (phantom tails)")
ax.invert_xaxis(); ax.set_xlabel("Hours before the close"); ax.set_ylabel("Mean absolute gap (percentage points)")
ax.set_title("With bids, the gap closes toward the close"); ax.legend(frameon=False, fontsize=8)
ax = axes[2]
bins = np.linspace(min(0.9, df.best_gross.min()), max(1.3, df.best_cost.quantile(.99)), 50)
ax.hist(df.best_gross, bins=bins, alpha=.55, color="#9db4d6", label="before fees")
ax.hist(df.best_cost, bins=bins, alpha=.75, color="#4a6fa5", label="after fees and spread")
ax.axvline(1.0, color="#b8520a", lw=1.5)
ax.set_xlabel("Cost of a package that pays at least $1"); ax.set_ylabel("Observations")
ax.set_title("No arbitrage: every package cost over $1"); ax.legend(frameon=False, fontsize=8)
fig.suptitle(f"Kalshi vs Polymarket, {INDEX_NAME} up or down, {df.date.min()} to {df.date.max()} ({df.date.nunique()} days)", y=1.02)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "cross_venue.png"), dpi=160, bbox_inches="tight")
print(f"\nWritten to {OUT}")
