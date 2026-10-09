"""Layer 5 on Bitcoin (pre-registered in research/PREREGISTRATION_BTC.md): do Kalshi's hourly BTC contracts agree with
Deribit's options, which predicts settlement better, and is the gap tradable after fees?

Run from the project root:
    SMOKE=1 python3 research/btc_options_vs_kalshi.py     data quality only: snapshots, pairing, fits, quoted counts
    python3 research/btc_options_vs_kalshi.py             full analysis; refuses to run before 2026-11-30
Before the full run (from collect/): python3 kalshi_history.py markets --series KXBTCD --since 2026-10-10
The quote filter, fee, trade rule and bootstrap are imported from research/options_vs_kalshi.py (stock layer 5).
Output: research/output/btc_options_vs_kalshi/
"""
import gzip, json, os, sys
from datetime import date
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
import options_vs_kalshi as L5
from implied.crypto import deribit_surface, at_time, YEAR

START, END, RUN_AFTER = "2026-10-10", "2026-11-27", date(2026, 11, 30)
SERIES, KK, DK = "KXBTCD", "kalshi_crypto", "deribit_btc"
SMOKE = os.environ.get("SMOKE") == "1"
OUT = os.path.join(ROOT, "research", "output", "btc_options_vs_kalshi")


def build_panel():
    L5.START, L5.END = START, END                       # git_files filters days on these
    files = L5.git_files()
    rows, log = [], []
    for day in sorted(files[KK]):
        kept, last = [], -10 ** 9
        for k in sorted(files[KK][day], key=L5.stamp_seconds):
            t = L5.stamp_seconds(k)
            if t - last >= L5.MIN_GAP_S:
                kept.append(k); last = t
        for k in kept:
            t = L5.stamp_seconds(k)
            krows = L5.load(k)
            collected = L5.utc(krows[0]["collected_utc"])
            near = min(files[DK].get(day, []), key=lambda o: abs(L5.stamp_seconds(o) - t), default=None)
            markets = [m for m in krows if m.get("type") == "market" and m.get("series") == SERIES
                       and m.get("strike_type") == "greater"]
            for ev in sorted({m["event_ticker"] for m in markets}):
                em = [m for m in markets if m["event_ticker"] == ev]
                close = L5.utc(em[0]["close_time"])
                secs = (close - collected).total_seconds()
                kind = "daily" if L5.utc(em[0]["open_time"]) <= close - pd.Timedelta(hours=2) else "hourly"
                rec = {"day": close.strftime("%Y-%m-%d"), "snap": krows[0]["collected_utc"], "event": ev, "kind": kind,
                       "paired": False, "fit": False, "n": len(em), "quoted": 0}
                log.append(rec)
                if secs < L5.MIN_TO_CLOSE_S or near is None or abs(L5.stamp_seconds(near) - t) > L5.MAX_PAIR_S:
                    continue
                rec["paired"] = True
                drows = L5.load(near)
                spot = float(drows[0]["index_price"])
                opts = [r for r in drows[1:] if r.get("type") == "option"]
                expiries = sorted({o["expiry"] for o in opts if L5.utc(o["expiry"]) >= close})
                try:
                    exp = L5.utc(expiries[0])
                    surf = at_time(deribit_surface(opts, exp, collected), secs / YEAR, spot)
                    c = surf.checks()
                    ok = abs(c["mass"] - 1) <= 0.05 and c["negative_mass"] < 0.01
                except Exception:
                    ok = False
                rec["fit"] = ok
                if not ok:
                    continue
                for m in em:
                    bid, ask, bsz, asz = L5.kalshi_quote(m)
                    K = float(m["floor_strike"])
                    covers = surf.in_fitted_range(K)
                    quoted = bid > 0 and ask is not None and ask - bid <= L5.MAX_SPREAD
                    rec["quoted"] += bool(quoted and covers)
                    rows.append({"day": rec["day"], "snap": rec["snap"], "hours_to_close": secs / 3600, "kind": kind,
                                 "event": ev, "ticker": m["ticker"], "strike": K, "bid": bid, "ask": ask,
                                 "bid_size": bsz, "ask_size": asz, "p_opt": float(surf.prob_above(K)),
                                 "spot": spot, "covers": covers, "quoted": bool(quoted)})
    return pd.DataFrame(rows), pd.DataFrame(log)


def main():
    os.makedirs(OUT, exist_ok=True)
    panel, log = build_panel()
    lines = [f"Bitcoin, window {START} to {END}. Data quality:"]
    if len(log):
        for kind, L in log.groupby("kind"):
            lines.append(f"  {kind:<6} event-snapshots {len(L)} on {L.day.nunique()} days; paired with Deribit {int(L.paired.sum())}; "
                         f"fit passed {int(L.fit.sum())}; contracts {int(L.n.sum())}; quoted and covered {int(L.quoted.sum())}")
    else:
        lines.append("  no Kalshi crypto snapshots in the window yet")
    if SMOKE:
        print("\n".join(lines))
        return
    if date.today() < RUN_AFTER:
        sys.exit(f"Pre-registered to run on or after {RUN_AFTER}. Use SMOKE=1 for data quality only.")

    mk = [json.loads(l) for l in gzip.open(os.path.join(ROOT, "data", "history", "kalshi", f"markets_{SERIES}.jsonl.gz"), "rt")]
    res = {m["ticker"]: m.get("result") for m in mk}
    panel["y"] = panel.ticker.map(lambda t: {"yes": 1.0, "no": 0.0}.get(res.get(t)))
    q = panel[panel.quoted & panel.covers & panel.y.notna()].copy()
    q["mid"] = (q.bid + q.ask) / 2
    q["inside"] = (q.p_opt >= q.bid) & (q.p_opt <= q.ask)
    q["gap"] = (q.p_opt - q.mid).abs()
    q["h"] = pd.cut(q.hours_to_close, [0, 1, 6, 25], labels=["<1h", "1-6h", "6-24h"])
    lines.append(f"  quoted contract-snapshots without a settlement found: {int((panel.quoted & panel.covers & panel.y.isna()).sum())}")

    lines.append("\nRule 1, agreement:")
    lines.append(f"  options inside Kalshi bid-ask {100 * q.inside.mean():.1f}%; mean |gap to mid| {100 * q.gap.mean():.2f}c; "
                 "by hours to close " + ", ".join(f"{h}: {100 * g.gap.mean():.2f}c" for h, g in q.groupby("h", observed=True)) +
                 "; by event " + ", ".join(f"{k}: {100 * g.gap.mean():.2f}c" for k, g in q.groupby("kind")))
    bk, bo = ((q.mid - q.y) ** 2).mean(), ((q.p_opt - q.y) ** 2).mean()
    lo, hi = L5.day_boot(q, lambda d: ((d.mid - d.y) ** 2).mean() - ((d.p_opt - d.y) ** 2).mean())
    v = "options more accurate" if lo > 0 else "Kalshi more accurate" if hi < 0 else "no detectable difference"
    lines.append(f"\nRule 2, accuracy (Brier; difference = Kalshi - options): Kalshi {bk:.4f}  options {bo:.4f}  "
                 f"diff {bk - bo:+.4f} ({lo:+.4f} to {hi:+.4f}) -> {v}")
    t = L5.trades(q, L5.THRESH)
    lines.append(f"\nRule 3, tradability (threshold {100 * L5.THRESH:.0f}c, >= {L5.MIN_SIZE} contracts shown, fee per 100-lot):")
    if len(t) == 0:
        lines.append("  no trades -> inconclusive")
    else:
        lo, hi = L5.day_boot(t, lambda d: d.pnl.mean())
        enough = len(t) >= 30 and t.day.nunique() >= 15
        v = "edge" if enough and lo > 0 else "no edge" if hi < 0 else "inconclusive"
        lines.append(f"  {len(t)} trades on {t.day.nunique()} days; mean {100 * t.pnl.mean():+.2f}c per contract "
                     f"({100 * lo:+.2f} to {100 * hi:+.2f}) -> {v}")
        t.to_csv(os.path.join(OUT, "trades.csv"), index=False)
        kinds = q.drop_duplicates("ticker").set_index("ticker").kind
        for name, sub in (("sell", t[t.side == "sell"]), ("buy", t[t.side == "buy"]), ("long shots", t[t.mid <= 0.05]),
                          ("hourly", t[t.ticker.map(kinds) == "hourly"]), ("5pm daily", t[t.ticker.map(kinds) == "daily"])):
            if len(sub):
                lines.append(f"      {name:<10} {len(sub):4d} trades, mean {100 * sub.pnl.mean():+.2f}c")
        for th, mid in ((0.02, False), (0.05, False), (L5.THRESH, True)):
            tt = L5.trades(q, th, use_mid=mid)
            if len(tt):
                lines.append(f"      sensitivity {'mid' if mid else 'touch'} {100 * th:.0f}c: {len(tt)} trades, mean {100 * tt.pnl.mean():+.2f}c")
    b = pd.cut(q.p_opt, [0, .02, .05, .1, .2, .4, .6, .8, .9, .95, .98, 1.0])
    tab = q.groupby(b, observed=True).agg(n=("y", "size"), pred=("p_opt", "mean"), won=("y", "mean"))
    lines.append("\nOptions probability calibration (reported only; checks the time scaling):\n" +
                 "\n".join(f"    {str(i):<12} n {r.n:5d}  predicted {r.pred:.3f}  settled yes {r.won:.3f}" for i, r in tab.iterrows()))
    txt = "\n".join(lines)
    print(txt)
    open(os.path.join(OUT, "summary.txt"), "w").write(txt + "\n")


if __name__ == "__main__":
    main()
