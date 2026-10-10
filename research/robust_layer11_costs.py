"""ROBUSTNESS (development sample only), checks suggested by the papers read on 2026-10-09:

1. Cost sweep (Rahimikia et al.: edges that vanish at realistic costs): layer 11's rule, 3h, with 0 to 3 extra cents
   per contract on top of Kalshi's fee (worse fills, wider real spreads).
2. Illiquidity, not mood? (Gottwald et al. attribute bear-day effects to illiquidity): selling the downside long shot,
   signal vs other days, controlling for the contract's own quoted spread and Bitcoin's realized volatility over the
   previous 7 days (known before the quote). Linear regression of profit per contract; intervals from 2,000 day
   resamples.
3. By price bucket (report results by bucket, not pooled): long-shot price 1-3c, 4-6c, 7-10c.
Changes nothing pre-registered.
"""
import os, sys
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
rng = np.random.default_rng(61)

q = pd.read_csv(os.path.join(ROOT, "research", "output", "explore_btc_sentiment.csv"))
q = q[q.side == "down"].copy()
q["signal"] = (q.fg <= 25) | (q.funding <= 0.0000149)
q["spread"] = q.ask - q.bid
q["ls_price"] = 1 - q.mid
d = pd.read_csv(os.path.join(ROOT, "data", "history", "crypto", "btc_daily.csv"), index_col=0, parse_dates=True)
r = np.log(d.Close).diff()
rv7 = (r.rolling(7).std() * np.sqrt(365)).shift(0)                 # through the day before the settlement day
rv7.index = (rv7.index + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
q["rv7"] = q.day.map(rv7)


def day_boot(df, fn, n=2000):
    days = df.day.unique(); g = {k: v for k, v in df.groupby("day")}
    out = []
    for _ in range(n):
        out.append(fn(pd.concat([g[k] for k in rng.choice(days, len(days))])))
    return np.nanpercentile(out, [2.5, 97.5])


s3 = q[q.h == 3]
print("1. Cost sweep, layer 11 rule (3h, signal days), extra cost per contract on top of the fee:")
for extra in (0, 0.01, 0.02, 0.03):
    x = s3[s3.signal]
    lo, hi = day_boot(x, lambda z: (z.pnl - extra).mean(), 1000)
    print(f"   +{100 * extra:.0f}c: {100 * (x.pnl - extra).mean():+.2f}c ({100 * lo:+.2f} to {100 * hi:+.2f}); "
          f"other days {100 * (s3[~s3.signal].pnl - extra).mean():+.2f}c")

print("\n2. Mood or illiquidity? Profit per contract regressed on signal, spread, 7-day realized vol (3h and 1h):")
for h in (3, 1):
    x = q[(q.h == h)].dropna(subset=["rv7"]).copy()
    def coef(z, cols):
        A = np.column_stack([np.ones(len(z))] + [z[c].astype(float).values for c in cols])
        return np.linalg.lstsq(A, z.pnl.values, rcond=None)[0][1]
    for cols, name in ((["signal"], "signal alone"), (["signal", "spread", "rv7"], "with spread and 7-day vol")):
        b = coef(x, cols); lo, hi = day_boot(x, lambda z: coef(z, cols))
        print(f"   {h}h, {name:<26}: signal-day effect {100 * b:+.2f}c ({100 * lo:+.2f} to {100 * hi:+.2f})")
    print(f"   {h}h: mean spread signal days {100 * x[x.signal].spread.mean():.1f}c vs {100 * x[~x.signal].spread.mean():.1f}c; "
          f"7-day vol {x[x.signal].rv7.mean():.0%} vs {x[~x.signal].rv7.mean():.0%}")

print("\n3. By long-shot price, 3h (signal days | other days):")
for lo_, hi_ in ((0.0, 0.035), (0.035, 0.065), (0.065, 0.101)):
    b = s3[(s3.ls_price > lo_) & (s3.ls_price <= hi_)]
    for name, z in (("signal", b[b.signal]), ("other", b[~b.signal])):
        if len(z) < 10:
            print(f"   {100 * lo_:.1f}-{100 * hi_:.1f}c {name}: too few ({len(z)})"); continue
        l, h = day_boot(z, lambda w: w.pnl.mean(), 1000)
        print(f"   {100 * lo_:.1f}-{100 * hi_:.1f}c {name:<6}: n {len(z):4d}, paid {(z.y == 0).mean():.1%}, "
              f"selling it {100 * z.pnl.mean():+.2f}c ({100 * l:+.2f} to {100 * h:+.2f})")
