# %% [markdown]
# # Phase 2: Are Kalshi's S&P 500 range contracts calibrated?
#
# Each trading day Kalshi lists a ladder of mutually exclusive contracts on where the S&P 500 closes
# (series KXINX). Exactly one pays $1. If prices are calibrated, contracts quoted at 20¢ should pay out
# about 20% of the time. This script measures that at several horizons before the close, tests for the
# favourite-longshot bias, and checks whether any gap survives the bid-ask spread and Kalshi's taker fee.
#
# Run from the project root:  python3 research/calibration.py
# Cells are marked with `# %%`, so VS Code can also run it as a notebook.

# %%
import glob, gzip, json, os, sys
from datetime import datetime
import numpy as np
import pandas as pd
from scipy.optimize import minimize
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST = os.path.join(ROOT, "data", "history", "kalshi")
OUT = os.path.join(ROOT, "research", "output", "calibration")
os.makedirs(OUT, exist_ok=True)
SERIES = "KXINX"
HORIZONS_H = [1, 3, 6, 24]      # hours before the 4pm ET close
MAX_STALENESS_H = 1.0           # the quote must come from within an hour of the target time
MAX_SPREAD = 0.10               # skip contracts quoted wider than 10 cents
FEE_RATE = 0.07                 # Kalshi taker fee: 0.07 * P * (1 - P) per contract (series fee_multiplier = 1)
BOOT = 500
rng = np.random.default_rng(7)

# %% Load settled markets
def read_jsonl(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(l) for l in f]

mk = pd.DataFrame(read_jsonl(os.path.join(HIST, f"markets_{SERIES}.jsonl.gz")))
mk = mk[mk["result"].isin(["yes", "no"])].copy()
mk["y"] = (mk["result"] == "yes").astype(int)
mk["close_ts"] = mk["close_time"].map(lambda s: int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()))
print(f"{len(mk):,} settled markets across {mk.event_ticker.nunique():,} trading days")

# %% Read one quote per market per horizon from the hourly candles
def dollars(block, field="close"):
    """Candle price blocks come as {'close_dollars': '0.12'} (new) or {'close': 12} in cents (old)."""
    if not block:
        return np.nan
    if block.get(f"{field}_dollars") not in (None, ""):
        return float(block[f"{field}_dollars"])
    if block.get(field) is not None:
        return float(block[field]) / 100
    return np.nan

rows, missing = [], 0
cdir = os.path.join(HIST, "candles_60m", SERIES)
for m in mk.itertuples():
    p = os.path.join(cdir, f"{m.ticker}.json.gz")
    if not os.path.exists(p):
        missing += 1
        continue
    with gzip.open(p, "rt", encoding="utf-8") as f:
        cs = json.load(f)["candlesticks"]
    if not cs:
        continue
    t = np.array([c["end_period_ts"] for c in cs])
    for h in HORIZONS_H:
        target = m.close_ts - h * 3600
        i = np.searchsorted(t, target, side="right") - 1
        if i < 0 or target - t[i] > MAX_STALENESS_H * 3600:
            continue
        c = cs[i]
        bid, ask = dollars(c.get("yes_bid")), dollars(c.get("yes_ask"))
        rows.append({"ticker": m.ticker, "event": m.event_ticker, "date": m.close_time[:10], "h": h,
                     "bid": bid, "ask": ask, "y": m.y, "strike_type": m.strike_type})
print(f"candle files missing for {missing:,} markets (pull them with collect/kalshi_history.py candles)")

q = pd.DataFrame(rows)
if q.empty:
    sys.exit("No usable quotes yet: pull hourly candles first (collect/kalshi_history.py candles --period 60 --series KXINX).")
q = q[(q.bid > 0) & (q.ask < 1) & (q.ask > q.bid) & (q.ask - q.bid <= MAX_SPREAD)].copy()
q["mid"] = (q.bid + q.ask) / 2
q["year"] = q.date.str[:4]
q.to_csv(os.path.join(OUT, "quotes.csv.gz"), index=False)
print(q.groupby("h").agg(quotes=("ticker", "size"), days=("event", "nunique"), median_spread=("ask", lambda s: (s - q.loc[s.index, "bid"]).median())))

# %% Calibration table with event-clustered bootstrap intervals
# Contracts on the same day are not independent (exactly one wins), so intervals resample whole days.
BINS = [0, .02, .05, .10, .20, .30, .40, .50, .60, .70, .80, .90, .95, .98, 1.0]

def cluster_boot(df, stat, n=BOOT):
    groups = {k: g for k, g in df.groupby("event")}
    keys = np.array(list(groups))
    out = []
    for _ in range(n):
        pick = rng.choice(keys, size=len(keys), replace=True)
        out.append(stat(pd.concat([groups[k] for k in pick])))
    return np.nanpercentile(out, [2.5, 97.5])

def calib_table(df):
    df = df.assign(bin=pd.cut(df.mid, BINS, include_lowest=True))
    t = df.groupby("bin", observed=True).agg(n=("y", "size"), price=("mid", "mean"), hit=("y", "mean"),
                                             days=("event", "nunique")).reset_index()
    lo, hi = [], []
    for b in t["bin"]:
        sub = df[df.bin == b]
        l, u = cluster_boot(sub, lambda d: d.y.mean(), n=200) if len(sub) >= 30 else (np.nan, np.nan)
        lo.append(l); hi.append(u)
    t["hit_lo"], t["hit_hi"] = lo, hi
    t["gap"] = t.hit - t.price
    return t

tables = {h: calib_table(q[q.h == h]) for h in HORIZONS_H}
for h, t in tables.items():
    print(f"\n--- {h}h before close ---")
    print(t[["bin", "n", "days", "price", "hit", "hit_lo", "hit_hi", "gap"]].to_string(index=False, float_format=lambda x: f"{x:.3f}"))

# %% Favourite-longshot test: fit P(win) = sigmoid(a + b * logit(price))
# b = 1 and a = 0 means calibrated. b > 1 means cheap contracts win less than priced and expensive ones more,
# i.e. long shots are overpriced (the favourite-longshot bias).
def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))

def fit_ab(df):
    x, y = logit(df.mid.values), df.y.values
    def nll(w):
        z = w[0] + w[1] * x
        return np.sum(np.logaddexp(0, z) - y * z)
    return minimize(nll, [0.0, 1.0], method="BFGS").x

def brier(df):
    return np.mean((df.mid - df.y) ** 2)

fl = []
for h in HORIZONS_H:
    d = q[q.h == h]
    a, b = fit_ab(d)
    b_lo, b_hi = cluster_boot(d, lambda s: fit_ab(s)[1], n=200)
    fl.append({"h": h, "quotes": len(d), "days": d.event.nunique(), "a": a, "b": b, "b_lo": b_lo, "b_hi": b_hi, "brier": brier(d)})
fl = pd.DataFrame(fl)
print("\nFavourite-longshot fit (b > 1 = long shots overpriced):")
print(fl.to_string(index=False, float_format=lambda x: f"{x:.3f}"))

# %% Does it survive costs? Expected profit per contract from crossing the spread and paying the taker fee.
# Buy YES at the ask: payoff y - ask - fee(ask).  Buy NO (sell YES) at the bid: (bid - y) - fee(bid).
def fee(p):
    return FEE_RATE * p * (1 - p)   # per contract; real fees round up per order, so this is a lower bound

q["pnl_yes"] = q.y - q.ask - fee(q.ask)
q["pnl_no"] = q.bid - q.y - fee(q.bid)
q["bin"] = pd.cut(q.mid, BINS, include_lowest=True)
pnl = []
for (h, b), g in q.groupby(["h", "bin"], observed=True):
    if len(g) < 100:
        continue
    for side in ("yes", "no"):
        col = f"pnl_{side}"
        lo, hi = cluster_boot(g, lambda d: d[col].mean(), n=200)
        pnl.append({"h": h, "bin": str(b), "side": side, "n": len(g), "mean_cents": 100 * g[col].mean(),
                    "lo_cents": 100 * lo, "hi_cents": 100 * hi})
pnl = pd.DataFrame(pnl)
pnl.to_csv(os.path.join(OUT, "pnl_by_bin.csv"), index=False)
sig = pnl[(pnl.lo_cents > 0)]
print("\nPrice bins where a taker side made money after spread and fees (95% interval above zero):")
print(sig.to_string(index=False, float_format=lambda x: f"{x:.2f}") if len(sig) else "none")

# %% Stability: the same fit year by year. An effect that flips sign across years is not one to trade.
by_year = []
for (h, yr), g in q.groupby(["h", "year"]):
    if g.event.nunique() < 40:
        continue
    a, b = fit_ab(g)
    by_year.append({"h": h, "year": yr, "days": g.event.nunique(), "b": b, "brier": brier(g)})
by_year = pd.DataFrame(by_year)
print("\nYear-by-year slope b:")
print(by_year.pivot(index="year", columns="h", values="b").to_string(float_format=lambda x: f"{x:.2f}"))

# %% Figures
fig, axes = plt.subplots(1, len(HORIZONS_H), figsize=(4.2 * len(HORIZONS_H), 4.2), sharey=True)
for ax, h in zip(axes, HORIZONS_H):
    t = tables[h]
    ax.plot([0, 1], [0, 1], color="#999", lw=1, ls="--", label="perfect calibration")
    ax.errorbar(t.price, t.hit, yerr=[t.hit - t.hit_lo, t.hit_hi - t.hit], fmt="o", ms=4, color="#b8520a",
                ecolor="#e2b48f", capsize=2, label="observed (95% CI, days resampled)")
    ax.set_title(f"{h}h before close  ·  b = {fl.loc[fl.h == h, 'b'].item():.2f}")
    ax.set_xlabel("Kalshi mid price")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.grid(alpha=.25)
axes[0].set_ylabel("Share that paid out")
axes[0].legend(loc="upper left", fontsize=8, frameon=False)
fig.suptitle(f"Kalshi S&P 500 daily range contracts ({SERIES}), {q.date.min()} to {q.date.max()}", y=1.02)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "calibration.png"), dpi=160, bbox_inches="tight")

fig, ax = plt.subplots(figsize=(7, 4))
t = tables[HORIZONS_H[0]]
ax.axhline(0, color="#999", lw=1)
ax.bar(range(len(t)), 100 * t.gap, color=["#b8520a" if g > 0 else "#4a6fa5" for g in t.gap])
ax.set_xticks(range(len(t))); ax.set_xticklabels([f"{b.left:.2f}–{b.right:.2f}" for b in t["bin"]], rotation=45, ha="right", fontsize=8)
ax.set_ylabel("Payout rate minus price (cents)")
ax.set_title(f"Mispricing by price bucket, {HORIZONS_H[0]}h before close")
fig.tight_layout()
fig.savefig(os.path.join(OUT, "gap_by_bin.png"), dpi=160)
print(f"\nFigures and tables written to {OUT}")
