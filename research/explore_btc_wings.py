"""Exploration, 2026-10-14 (after the fact): layer 5 Bitcoin P&L split by bet type. Origin of layer 5s; not evidence."""
import sys, os
sys.path.insert(0, "trade"); sys.path.insert(0, "research")
import paper as P
import pandas as pd
trades, res = P.all_trades("paper_btc", "paper_btc_results")
rows = []
for d, ts in trades.items():
    for t in ts:
        r = res.get(d, {}).get(t["ticker"])
        if not r: continue
        away = (t["side"] == "buy") == (t["strike"] > t["spot"])   # betting price ends farther from spot than Kalshi thinks
        rows.append(dict(snap=pd.Timestamp(t["snap"]), kind=t["kind"], side=t["side"],
                         bet="bigger move" if away else "smaller move", pnl=P.pnl_of(t, r),
                         dist=abs(t["strike"] / t["spot"] - 1) * 100))
df = pd.DataFrame(rows)
cut = pd.Timestamp("2026-10-14T03:00:00Z")   # Tue 20:00 PT
for name, g in (("all history", df), ("before Tue 8pm PT", df[df.snap < cut]), ("since Tue 8pm PT", df[df.snap >= cut])):
    print(f"\n{name}: {len(g)} trades, ${g.pnl.sum():,.2f}")
    print(g.groupby(["bet"]).pnl.agg(["count", "sum", lambda s: (s > 0).mean()]).round(2).to_string())
    print(g.groupby(["kind"]).pnl.agg(["count", "sum"]).round(2).to_string())
print("\nshare of trades betting on a bigger move:", round((df.bet == "bigger move").mean(), 2))
