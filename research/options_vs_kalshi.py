"""Layer 5 (pre-registered in research/PREREGISTRATION_LAYER5.md): do Kalshi's daily index ranges agree with the
options market, which predicts settlement better, and is the gap tradable after fees?

Run from the project root:
    SMOKE=1 python3 research/options_vs_kalshi.py     data quality only: snapshots, pairing, fit success, quoted counts
    python3 research/options_vs_kalshi.py             full analysis; refuses to run before 2026-11-30
Reads the cloud `data` branch (git fetch origin data). Output: research/output/options_vs_kalshi/
"""
import gzip, io, json, math, os, subprocess, sys
from collections import defaultdict
from datetime import datetime, timezone, date
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from implied import surface_from_snapshot
from implied.kalshi_ladder import make_ladder

START, END, RUN_AFTER = "2026-10-05", "2026-11-27", date(2026, 11, 30)
PAIRS = {"KXINX": ("spx_options", "SPXW"), "KXNASDAQ100": ("ndx_options", "NDXP")}
NAMES = {"KXINX": "S&P 500", "KXNASDAQ100": "Nasdaq-100"}
MAX_PAIR_S, MIN_GAP_S, MIN_TO_CLOSE_S = 180, 600, 300
MAX_SPREAD, THRESH, MIN_SIZE, FEE_RATE, N_BOOT = 0.10, 0.03, 100, 0.07, 2000
SMOKE = os.environ.get("SMOKE") == "1"
OUT = os.path.join(ROOT, "research", "output", "options_vs_kalshi")
rng = np.random.default_rng(5)


def num(x):
    try:
        v = float(str(x).replace(",", ""))
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def utc(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def stamp_seconds(name):                    # kalshi_132437Z.jsonl.gz -> seconds after midnight UTC
    s = name.split("_")[-1][:6]
    return int(s[:2]) * 3600 + int(s[2:4]) * 60 + int(s[4:6])


def git_files():
    subprocess.run(["git", "fetch", "-q", "origin", "data"], cwd=ROOT, check=True)
    names = subprocess.run(["git", "ls-tree", "-r", "--name-only", "origin/data"], cwd=ROOT,
                           capture_output=True, text=True, check=True).stdout.split()
    by = defaultdict(lambda: defaultdict(list))            # by[kind][day] -> [paths]
    for n in names:
        p = n.split("/")
        if len(p) == 5 and p[0] == "data" and p[1] == "raw" and START <= p[3] <= END:
            by[p[2]][p[3]].append(n)
    return by


def load(path):
    b = subprocess.run(["git", "show", f"origin/data:{path}"], cwd=ROOT, capture_output=True, check=True).stdout
    return [json.loads(l) for l in gzip.open(io.BytesIO(b), "rt")]


def kalshi_quote(m):
    bid = num(m.get("yes_bid_dollars")) or 0.0
    ask = num(m.get("yes_ask_dollars"))
    if ask is not None and (ask >= 1.0 or (num(m.get("yes_ask_size_fp")) or 0) == 0):
        ask = None
    return bid, ask, num(m.get("yes_bid_size_fp")) or 0.0, num(m.get("yes_ask_size_fp")) or 0.0


def build_panel():
    files = git_files()
    rows, log = [], []
    for day in sorted(files["kalshi"]):
        ks = sorted(files["kalshi"][day], key=stamp_seconds)
        kept, last = [], -10 ** 9
        for k in ks:
            t = stamp_seconds(k)
            if 13 * 3600 + 1800 <= t <= 20 * 3600 and t - last >= MIN_GAP_S:
                kept.append(k); last = t
        for k in kept:
            t = stamp_seconds(k)
            krows = load(k)
            collected = krows[0]["collected_utc"]
            markets = [m for m in krows if m.get("type") == "market"]
            for series, (kind, root) in PAIRS.items():
                opts = files[kind].get(day, [])
                near = min(opts, key=lambda o: abs(stamp_seconds(o) - t), default=None)
                rec = {"day": day, "snap": collected, "series": series, "paired": False, "fit": False, "n": 0, "quoted": 0}
                log.append(rec)
                if near is None or abs(stamp_seconds(near) - t) > MAX_PAIR_S:
                    continue
                rec["paired"] = True
                ms = [m for m in markets if m.get("series") == series and m["close_time"][:10] == day]
                if not ms:
                    continue
                close = utc(ms[0]["close_time"])
                secs = (close - utc(collected)).total_seconds()
                if secs < MIN_TO_CLOSE_S:
                    continue
                orows = load(near)
                head, olist = orows[0], [r for r in orows[1:] if r.get("type") == "option"]
                try:
                    surf = surface_from_snapshot(olist, day, secs / (365 * 86400), spot_guess=num(head.get("spot")), root=root)
                    c = surf.checks()
                    ok = abs(c["mass"] - 1) <= 0.05 and c["negative_mass"] < 0.01
                except Exception:
                    ok = False
                rec["fit"] = ok
                if not ok:
                    continue
                for ev in sorted({m["event_ticker"] for m in ms}):
                    em = [m for m in ms if m["event_ticker"] == ev]
                    types = [m.get("strike_type") for m in em]
                    if not (types.count("less") == 1 and types.count("greater") == 1):
                        continue                        # not a full range ladder
                    q = [dict(zip(("bid", "ask", "bid_size", "ask_size"), kalshi_quote(m))) for m in em]
                    lad = make_ladder([{**m, **qq} for m, qq in zip(em, q)])
                    for _, r in lad.iterrows():
                        lo = None if np.isinf(r.lo) else float(r.lo)
                        hi = None if np.isinf(r.hi) else float(r.hi)
                        covers = all(surf.in_fitted_range(x) for x in (lo, hi) if x is not None)
                        p = surf.prob_between(lo, hi)
                        ask = None if pd.isna(r.ask) else float(r.ask)
                        quoted = r.bid > 0 and ask is not None and ask - r.bid <= MAX_SPREAD
                        rec["n"] += 1; rec["quoted"] += bool(quoted and covers)
                        rows.append({"day": day, "snap": collected, "hours_to_close": secs / 3600, "series": series,
                                     "event": ev, "ticker": r.ticker, "lo": lo, "hi": hi, "bid": r.bid, "ask": ask,
                                     "bid_size": r.bid_size, "ask_size": r.ask_size, "p_opt": float(p),
                                     "covers": covers, "quoted": bool(quoted)})
    return pd.DataFrame(rows), pd.DataFrame(log)


def fee100(p):
    return math.ceil(round(100 * FEE_RATE * p * (1 - p) * 100, 6)) / 100 / 100


def day_boot(df, stat):
    days = df.day.unique()
    groups = {d: g for d, g in df.groupby("day")}
    out = []
    for _ in range(N_BOOT):
        pick = rng.choice(days, len(days))
        out.append(stat(pd.concat([groups[d] for d in pick])))
    return np.nanpercentile(out, [2.5, 97.5])


def trades(q, thresh, use_mid=False):
    t = []
    for (day, tk), g in q.sort_values("snap").groupby(["day", "ticker"]):
        for _, r in g.iterrows():
            ref_b = (r.bid + r.ask) / 2 if use_mid else r.bid
            ref_a = (r.bid + r.ask) / 2 if use_mid else r.ask
            if ref_b - r.p_opt > thresh and r.bid_size >= MIN_SIZE:
                t.append({"day": day, "ticker": tk, "side": "sell", "price": r.bid, "mid": (r.bid + r.ask) / 2,
                          "pnl": r.bid - r.y - fee100(r.bid)}); break
            if r.p_opt - ref_a > thresh and r.ask_size >= MIN_SIZE:
                t.append({"day": day, "ticker": tk, "side": "buy", "price": r.ask, "mid": (r.bid + r.ask) / 2,
                          "pnl": r.y - r.ask - fee100(r.ask)}); break
    return pd.DataFrame(t)


def main():
    os.makedirs(OUT, exist_ok=True)
    panel, log = build_panel()
    lines = [f"Window {START} to {END}. Data quality:"]
    for s in PAIRS:
        L = log[log.series == s]
        lines.append(f"  {NAMES[s]:<10} snapshots {len(L)} on {L.day.nunique()} days; paired with options {int(L.paired.sum())}; "
                     f"fit passed {int(L.fit.sum())}; contract-snapshots {int(L.n.sum())}; quoted and covered {int(L.quoted.sum())}")
    if SMOKE:
        print("\n".join(lines))
        return
    if date.today() < RUN_AFTER:
        sys.exit(f"Pre-registered to run on or after {RUN_AFTER}. Use SMOKE=1 for data quality only.")
    panel.to_csv(os.path.join(OUT, "panel.csv.gz"), index=False)

    mk = []
    for s in PAIRS:
        p = os.path.join(ROOT, "data", "history", "kalshi", f"markets_{s}.jsonl.gz")
        mk += [json.loads(l) for l in gzip.open(p, "rt")]
    res = {m["ticker"]: m.get("result") for m in mk}
    panel["y"] = panel.ticker.map(lambda t: {"yes": 1.0, "no": 0.0}.get(res.get(t)))
    q = panel[panel.quoted & panel.covers & panel.y.notna()].copy()
    q["mid"] = (q.bid + q.ask) / 2
    q["inside"] = (q.p_opt >= q.bid) & (q.p_opt <= q.ask)
    q["gap"] = (q.p_opt - q.mid).abs()
    q["h"] = pd.cut(q.hours_to_close, [0, 2, 4, 6.6], labels=["2-0", "4-2", "6-4"])
    unsettled = panel.quoted & panel.covers & panel.y.isna()
    lines.append(f"  quoted contract-snapshots without a settlement found: {int(unsettled.sum())}")

    lines.append("\nRule 1, agreement:")
    for s in PAIRS:
        g = q[q.series == s]
        lines.append(f"  {NAMES[s]:<10} options inside Kalshi bid-ask {100 * g.inside.mean():.1f}%; mean |gap to mid| "
                     f"{100 * g.gap.mean():.2f}c; by hours to close " +
                     ", ".join(f"{h}: {100 * gg.gap.mean():.2f}c" for h, gg in g.groupby("h", observed=True)))
    lines.append("\nRule 2, accuracy (Brier, lower is better; difference = Kalshi - options):")
    for s in PAIRS:
        g = q[q.series == s]
        bk, bo = ((g.mid - g.y) ** 2).mean(), ((g.p_opt - g.y) ** 2).mean()
        lo, hi = day_boot(g, lambda d: ((d.mid - d.y) ** 2).mean() - ((d.p_opt - d.y) ** 2).mean())
        v = "options more accurate" if lo > 0 else "Kalshi more accurate" if hi < 0 else "no detectable difference"
        lines.append(f"  {NAMES[s]:<10} Kalshi {bk:.4f}  options {bo:.4f}  diff {bk - bo:+.4f} ({lo:+.4f} to {hi:+.4f}) -> {v}")
    lines.append(f"\nRule 3, tradability (threshold {100 * THRESH:.0f}c, >= {MIN_SIZE} contracts shown, fee per 100-lot):")
    for s in PAIRS:
        t = trades(q[q.series == s], THRESH)
        if len(t) == 0:
            lines.append(f"  {NAMES[s]:<10} no trades -> inconclusive"); continue
        lo, hi = day_boot(t, lambda d: d.pnl.mean())
        enough = len(t) >= 30 and t.day.nunique() >= 15
        v = ("edge" if enough and lo > 0 else "no edge" if hi < 0 else "inconclusive")
        lines.append(f"  {NAMES[s]:<10} {len(t)} trades on {t.day.nunique()} days; mean {100 * t.pnl.mean():+.2f}c per contract "
                     f"({100 * lo:+.2f} to {100 * hi:+.2f}) -> {v}")
        t.to_csv(os.path.join(OUT, f"trades_{s}.csv"), index=False)
        for name, sub in (("sell", t[t.side == "sell"]), ("buy", t[t.side == "buy"]), ("long shots", t[t.mid <= 0.05])):
            if len(sub):
                lines.append(f"      {name:<10} {len(sub):4d} trades, mean {100 * sub.pnl.mean():+.2f}c")
        for th, mid in ((0.02, False), (0.05, False), (THRESH, True)):
            tt = trades(q[q.series == s], th, use_mid=mid)
            if len(tt):
                lines.append(f"      sensitivity {'mid' if mid else 'touch'} {100 * th:.0f}c: {len(tt)} trades, mean {100 * tt.pnl.mean():+.2f}c")
    lines.append("\nOptions probability calibration (reported only):")
    for s in PAIRS:
        g = q[q.series == s]
        b = pd.cut(g.p_opt, [0, .02, .05, .1, .2, .4, .6, .8, 1.0])
        tab = g.groupby(b, observed=True).agg(n=("y", "size"), pred=("p_opt", "mean"), won=("y", "mean"))
        lines.append(f"  {NAMES[s]}:\n" + "\n".join(f"    {str(i):<12} n {r.n:5d}  predicted {r.pred:.3f}  settled yes {r.won:.3f}"
                                                   for i, r in tab.iterrows()))
    txt = "\n".join(lines)
    print(txt)
    open(os.path.join(OUT, "summary.txt"), "w").write(txt + "\n")


if __name__ == "__main__":
    main()
