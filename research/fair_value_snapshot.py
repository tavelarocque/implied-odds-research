# %% [markdown]
# # Layer 5 preview: option-implied odds vs Kalshi, one snapshot
#
# For each Kalshi S&P 500 daily range event (KXINX) that has a matching PM-settled SPXW expiry, fit the option
# smile, turn it into a probability for every Kalshi range (Breeden-Litzenberger), and line it up against the
# Kalshi quote. One snapshot is an anecdote, not evidence: the point is to see the pipeline work end to end.
#
# Run from the project root:  python3 research/fair_value_snapshot.py [path/to/spx_options.jsonl.gz]
# With no argument it uses the most recent snapshot pair in data/raw/.

# %%
import glob, gzip, json, os, sys
from datetime import datetime
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from implied import surface_from_snapshot

RAW = os.path.join(ROOT, "data", "raw")
OUT = os.path.join(ROOT, "research", "output", "fair_value")
os.makedirs(OUT, exist_ok=True)


def read(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(l) for l in f]


opt_path = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob(os.path.join(RAW, "spx_options", "*", "*.gz")))[-1]
stamp = os.path.basename(opt_path).split("_")[-1].split(".")[0]          # e.g. 201802Z
day = os.path.basename(os.path.dirname(opt_path))
kal_candidates = sorted(glob.glob(os.path.join(RAW, "kalshi", day, "*.gz")))
kal_path = min(kal_candidates, key=lambda p: abs(int(os.path.basename(p).split("_")[-1][:6]) - int(stamp[:6])))
opts, kal = read(opt_path), read(kal_path)
head = opts[0]
print(f"options: {os.path.relpath(opt_path, ROOT)}  spot {head['spot']}  feed time {head['feed_timestamp']}")
print(f"kalshi:  {os.path.relpath(kal_path, ROOT)}")

# %% Match each Kalshi daily event to the SPXW expiry that settles on the same 4pm close
def money(x):
    return None if x in (None, "") else float(x)

markets = [m for m in kal if m.get("type") == "market" and m.get("series") == "KXINX"]
events = sorted({m["event_ticker"] for m in markets})
rows = []
for ev in events:
    ms = [m for m in markets if m["event_ticker"] == ev]
    expiry = ms[0]["close_time"][:10]
    # Only total variance matters for probabilities, so any consistent time unit works; use calendar years.
    T = max((datetime.fromisoformat(ms[0]["close_time"].replace("Z", "+00:00")) -
             datetime.fromisoformat(head["collected_utc"])).total_seconds(), 3600) / (365 * 86400)
    try:
        surf = surface_from_snapshot(opts[1:], expiry, T, spot_guess=head["spot"])
    except ValueError as e:
        print(f"{ev}: no option fit ({e})")
        continue
    chk = surf.checks()
    print(f"\n{ev} (expiry {expiry}): forward {surf.F:.1f}, ATM vol {float(surf.sigma(surf.F)):.1%} annualized, "
          f"density mass {chk['mass']:.3f}, negative mass {chk['negative_mass']:.4f}")
    for m in ms:
        lo, hi = money(m.get("floor_strike")), money(m.get("cap_strike"))
        st = m.get("strike_type")
        if st == "greater":
            p_opt, label, hi = surf.prob_between(lo, None), f"> {lo:,.0f}", None
        elif st == "less":
            p_opt, label, lo = surf.prob_between(None, hi), f"< {hi:,.0f}", None
        else:
            p_opt, label = surf.prob_between(lo, hi), f"{lo:,.0f} to {hi:,.0f}"
        bid, ask = money(m.get("yes_bid_dollars")), money(m.get("yes_ask_dollars"))
        edge_k = [x for x in (lo, hi) if x is not None]
        rows.append({"event": ev, "range": label, "lo": lo, "hi": hi, "bid": bid, "ask": ask,
                     "mid": (bid + ask) / 2 if bid is not None and ask is not None else np.nan,
                     "p_options": p_opt, "fit_covers": all(surf.in_fitted_range(x) for x in edge_k)})

df = pd.DataFrame(rows)
df["inside_spread"] = (df.p_options >= df.bid) & (df.p_options <= df.ask)
df["gap_vs_mid"] = df.p_options - df.mid
df = df.sort_values(["event", "lo"], na_position="first")
df.to_csv(os.path.join(OUT, f"fair_value_{day}_{stamp}.csv"), index=False)

# %% Summary: does the option-implied probability sit inside Kalshi's bid-ask, and how big are the gaps?
for ev, g in df.groupby("event"):
    q = g[(g.ask - g.bid) <= 0.10]                 # quoted contracts only
    print(f"\n{ev}: {len(g)} contracts, {len(q)} with a spread of 10c or less")
    print(f"  option-implied probability inside Kalshi's bid-ask: {q.inside_spread.mean():.0%} of quoted contracts")
    print(f"  mean absolute gap to Kalshi mid: {100 * q.gap_vs_mid.abs().mean():.1f} pp; sum of Kalshi mids {g.mid.sum():.3f} "
          f"(1.0 would be a fair ladder), sum of option probabilities {g.p_options.sum():.3f}")
    show = g.loc[(g.mid > 0.02) | (g.p_options > 0.02), ["range", "bid", "ask", "p_options", "gap_vs_mid", "inside_spread"]]
    print(show.to_string(index=False, float_format=lambda x: f"{x:.3f}"))

# %% Figure: one panel per event
evs = list(df.event.unique())
fig, axes = plt.subplots(len(evs), 1, figsize=(11, 3.6 * len(evs)), squeeze=False)
for ax, ev in zip(axes[:, 0], evs):
    g = df[(df.event == ev) & ((df.mid > 0.005) | (df.p_options > 0.005))]
    x = np.arange(len(g))
    ax.vlines(x, g.bid, g.ask, color="#4a6fa5", lw=6, alpha=.45, label="Kalshi bid–ask")
    ax.plot(x, g.p_options, "o", color="#b8520a", ms=5, label="option-implied (Breeden–Litzenberger)")
    ax.set_xticks(x); ax.set_xticklabels(g["range"], rotation=60, ha="right", fontsize=7)
    ax.set_ylabel("Probability"); ax.set_title(f"{ev}: Kalshi quotes vs option-implied probabilities"); ax.grid(alpha=.25)
axes[0, 0].legend(frameon=False, fontsize=8)
fig.tight_layout()
fig.savefig(os.path.join(OUT, f"fair_value_{day}_{stamp}.png"), dpi=150)
print(f"\nWritten to {OUT}")
