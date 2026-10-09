"""Paper trader for layer 5's trading rule (research/PREREGISTRATION_LAYER5.md, rule 3), run live after every snapshot.

The rule, unchanged: on the same-day range ladder, sell YES at the bid when the options probability is more than
3 cents below it, or buy YES at the ask when it is more than 3 cents above it, if the book shows at least 100
contracts at that price. One trade per contract per day (the first signal), held to settlement, Kalshi's taker fee per
100-lot. Constants and helpers are imported from research/options_vs_kalshi.py so the two cannot drift apart.

What this adds over the layer 5 backtest: each decision is written to the data branch by the run that made it, so git
timestamps it and it cannot use anything from later in the day. It also records how much money each trade ties up,
which is what a real account would need. Each run also asks Kalshi for the result of every unsettled trade and records
it in data/raw/paper_results/<day>.json. Outcomes are watched trade by trade from 2026-10-09 (Tave's call); the rule
itself is frozen until the layer 5 analysis on 2026-11-30, and `report` (the pooled verdict) still waits for that date.

Run from the project root:
    python3 trade/paper.py live            evaluate this run's snapshot (the GitHub workflow calls this)
    python3 trade/paper.py live --btc      the same for Bitcoin (research/PREREGISTRATION_BTC.md; crypto workflow)
    python3 trade/paper.py replay          rerun the rule over the window so far from the data branch, decisions only
    python3 trade/paper.py replay --check  also confirm the replay matches layer 5's own trade logic exactly
    python3 trade/paper.py digest [N]      the last N stock trading days' trades and the last N x 24 h of Bitcoin
                                           trades, and whether each won (default 1)
    python3 trade/paper.py report          on or after 2026-11-30: settle the live log; profit, capital, worst day
"""
import glob, gzip, io, json, os, subprocess, sys
from datetime import datetime, timezone, date
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
import options_vs_kalshi as L5
from implied import surface_from_snapshot
from implied.kalshi_ladder import make_ladder

QTY = L5.MIN_SIZE                       # 100 contracts per trade: the size the rule requires the book to show
RAW = os.path.join(ROOT, "data", "raw")
OPEN_S, CLOSE_S = 13 * 3600 + 1800, 20 * 3600
MAX_AGE_S = 900                         # live mode ignores a snapshot older than this (stale local files)
OUT = os.path.join(ROOT, "research", "output", "paper")


def signals(krows, opts, day):
    """Every rule-3 signal in one Kalshi snapshot. opts maps series -> rows of the paired options snapshot."""
    collected = krows[0]["collected_utc"]
    markets = [m for m in krows if m.get("type") == "market"]
    out, notes = [], {}
    for series, (kind, root) in L5.PAIRS.items():
        orows = opts.get(series)
        if orows is None:
            notes[series] = "no options snapshot within 3 minutes"; continue
        ms = [m for m in markets if m.get("series") == series and m["close_time"][:10] == day]
        if not ms:
            notes[series] = "no same-day ladder"; continue
        secs = (L5.utc(ms[0]["close_time"]) - L5.utc(collected)).total_seconds()
        if secs < L5.MIN_TO_CLOSE_S:
            notes[series] = "under 5 minutes to close"; continue
        head, olist = orows[0], [r for r in orows[1:] if r.get("type") == "option"]
        try:
            surf = surface_from_snapshot(olist, day, secs / (365 * 86400), spot_guess=L5.num(head.get("spot")), root=root)
            c = surf.checks()
            ok = abs(c["mass"] - 1) <= 0.05 and c["negative_mass"] < 0.01
        except Exception:
            ok = False
        if not ok:
            notes[series] = "options fit failed its checks"; continue
        n = 0
        for ev in sorted({m["event_ticker"] for m in ms}):
            em = [m for m in ms if m["event_ticker"] == ev]
            types = [m.get("strike_type") for m in em]
            if not (types.count("less") == 1 and types.count("greater") == 1):
                continue
            q = [dict(zip(("bid", "ask", "bid_size", "ask_size"), L5.kalshi_quote(m))) for m in em]
            lad = make_ladder([{**m, **qq} for m, qq in zip(em, q)])
            for _, r in lad.iterrows():
                lo = None if np.isinf(r.lo) else float(r.lo)
                hi = None if np.isinf(r.hi) else float(r.hi)
                if not all(surf.in_fitted_range(x) for x in (lo, hi) if x is not None):
                    continue
                ask = None if pd.isna(r.ask) else float(r.ask)
                if not (r.bid > 0 and ask is not None and ask - r.bid <= L5.MAX_SPREAD):
                    continue
                n += 1
                p = float(surf.prob_between(lo, hi))
                base = {"type": "trade", "day": day, "snap": collected, "series": series, "event": ev,
                        "ticker": r.ticker, "lo": lo, "hi": hi, "bid": float(r.bid), "ask": ask,
                        "bid_size": float(r.bid_size), "ask_size": float(r.ask_size), "p_opt": p,
                        "hours_to_close": secs / 3600}
                if r.bid - p > L5.THRESH and r.bid_size >= L5.MIN_SIZE:
                    out.append(sized({**base, "side": "sell", "price": float(r.bid)}))
                elif p - ask > L5.THRESH and r.ask_size >= L5.MIN_SIZE:
                    out.append(sized({**base, "side": "buy", "price": ask}))
        notes[series] = f"evaluated {n} quoted contracts"
    return out, notes


def sized(t):
    """Fee and the money a 100-lot ties up until settlement (a sold YES risks 1 - price per contract)."""
    fee = L5.fee100(t["price"]) * QTY
    risk = t["price"] if t["side"] == "buy" else 1 - t["price"]
    return {**t, "qty": QTY, "fee": round(fee, 2), "capital": round(QTY * risk + fee, 2)}


def read_gz(path=None, blob=None):
    f = gzip.open(path, "rt") if path else gzip.open(io.BytesIO(blob), "rt")
    return [json.loads(l) for l in f]


def logged_runs(day, log="paper"):
    """Paper files already on the data branch for this day: (seconds, rows) per earlier run."""
    # GitHub's checkout has no origin/data ref, so name it explicitly. Same objects the workflow's save step fetches.
    subprocess.run(["git", "fetch", "-q", "origin", "+refs/heads/data:refs/remotes/origin/data"], cwd=ROOT, check=True)
    names = subprocess.run(["git", "ls-tree", "-r", "--name-only", "origin/data", f"data/raw/{log}/{day}/"],
                           cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    return [(L5.stamp_seconds(n), L5.load(n)) for n in sorted(names, key=L5.stamp_seconds)]


def live():
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    ks = sorted(glob.glob(os.path.join(RAW, "kalshi", day, "kalshi_*Z.jsonl.gz")), key=L5.stamp_seconds)
    if not ks:
        print("paper: no Kalshi snapshot from today on disk"); return
    kpath = ks[-1]
    krows = read_gz(kpath)
    t = L5.stamp_seconds(kpath)
    age = (now - L5.utc(krows[0]["collected_utc"])).total_seconds()
    run = {"type": "run", "day": day, "snap": krows[0]["collected_utc"], "decided_utc": now.isoformat(),
           "commit": os.environ.get("GITHUB_SHA", "local"), "evaluated": False}
    if age > MAX_AGE_S:
        print(f"paper: newest snapshot is {age:.0f} s old, not trading on it"); return
    earlier = logged_runs(day)
    evaluated = [s for s, rows in earlier if rows and rows[0].get("evaluated")]
    traded = {r["ticker"] for _, rows in earlier for r in rows if r.get("type") == "trade"}
    trades = []
    if not OPEN_S <= t <= CLOSE_S:
        run["reason"] = "outside 13:30-20:00 UTC"
    elif evaluated and t - evaluated[-1] < L5.MIN_GAP_S:
        run["reason"] = "within 10 minutes of the last evaluated snapshot"
    else:
        opts = {}
        for series, (kind, _) in L5.PAIRS.items():
            files = glob.glob(os.path.join(RAW, kind, day, f"{kind}_*Z.jsonl.gz"))
            near = min(files, key=lambda o: abs(L5.stamp_seconds(o) - t), default=None)
            if near is not None and abs(L5.stamp_seconds(near) - t) <= L5.MAX_PAIR_S:
                opts[series] = read_gz(near)
        sig, notes = signals(krows, opts, day)
        trades = [s for s in sig if s["ticker"] not in traded]
        run.update(evaluated=True, notes=notes, signals=len(sig), new_trades=len(trades))
    d = os.path.join(RAW, "paper", day)
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, f"paper_{os.path.basename(kpath).split('_')[-1]}")
    with gzip.open(out, "wt") as f:
        for r in [run] + trades:
            f.write(json.dumps(r) + "\n")
    print(f"paper: {run.get('reason') or run['notes']}; {len(trades)} new trades -> {os.path.relpath(out, ROOT)}")
    for x in trades:
        print(f"  {x['side']:<4} {x['qty']} {x['ticker']} at {100 * x['price']:.0f}c (options {100 * x['p_opt']:.1f}c), "
              f"ties up ${x['capital']:.2f}")
    try:
        settle(extra={day: trades})
    except Exception as e:                                  # settling can wait for the next run
        print(f"paper: settlement check failed ({e}); will retry next run")


def btc_signal(r):
    """Layer 5's rule on one Bitcoin contract row (research/btc_options_vs_kalshi.py), same order as L5.trades."""
    if not (r["quoted"] and r["covers"]):
        return None
    base = {"type": "trade", "series": "KXBTCD", **{k: r[k] for k in ("day", "snap", "event", "ticker", "strike", "bid",
            "ask", "bid_size", "ask_size", "p_opt", "spot", "hours_to_close", "kind")}}
    if r["bid"] - r["p_opt"] > L5.THRESH and r["bid_size"] >= L5.MIN_SIZE:
        return sized({**base, "side": "sell", "price": float(r["bid"])})
    if r["p_opt"] - r["ask"] > L5.THRESH and r["ask_size"] >= L5.MIN_SIZE:
        return sized({**base, "side": "buy", "price": float(r["ask"])})
    return None


def live_btc():
    """The Bitcoin version (research/PREREGISTRATION_BTC.md), run by .github/workflows/crypto.yml after each snapshot.
    Logs to data/raw/paper_btc/, results to data/raw/paper_btc_results/."""
    import btc_options_vs_kalshi as BTC
    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    ks = sorted(glob.glob(os.path.join(RAW, BTC.KK, day, f"{BTC.KK}_*Z.jsonl.gz")), key=L5.stamp_seconds)
    if not ks:
        print("paper btc: no Kalshi crypto snapshot from today on disk"); return
    kpath = ks[-1]
    krows = read_gz(kpath)
    t = L5.stamp_seconds(kpath)
    age = (now - L5.utc(krows[0]["collected_utc"])).total_seconds()
    if age > MAX_AGE_S:
        print(f"paper btc: newest snapshot is {age:.0f} s old, not trading on it"); return
    run = {"type": "run", "day": day, "snap": krows[0]["collected_utc"], "decided_utc": now.isoformat(),
           "commit": os.environ.get("GITHUB_SHA", "local"), "evaluated": False}
    yday = (now - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    earlier, before = logged_runs(day, "paper_btc"), logged_runs(yday, "paper_btc")
    evaluated = [s for s, rows in earlier if rows and rows[0].get("evaluated")]
    traded = {r["ticker"] for _, rows in earlier + before for r in rows if r.get("type") == "trade"}
    trades = []
    if evaluated and t - evaluated[-1] < L5.MIN_GAP_S:
        run["reason"] = "within 10 minutes of the last evaluated snapshot"
    else:
        files = glob.glob(os.path.join(RAW, BTC.DK, day, f"{BTC.DK}_*Z.jsonl.gz"))
        near = min(files, key=lambda o: abs(L5.stamp_seconds(o) - t), default=None)
        drows = read_gz(near) if near is not None and abs(L5.stamp_seconds(near) - t) <= L5.MAX_PAIR_S else None
        log, rows = BTC.snapshot_rows(krows, drows)
        sig = [x for x in map(btc_signal, rows) if x]
        trades = [x for x in sig if x["ticker"] not in traded]
        run.update(evaluated=True, notes={r["event"]: ("fit failed" if r["paired"] and not r["fit"] else
                   "no Deribit snapshot or under 5 minutes" if not r["paired"] else f"{r['quoted']} quoted") for r in log},
                   signals=len(sig), new_trades=len(trades))
    d = os.path.join(RAW, "paper_btc", day)
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, f"paper_btc_{os.path.basename(kpath).split('_')[-1]}")
    with gzip.open(out, "wt") as f:
        for r in [run] + trades:
            f.write(json.dumps(r) + "\n")
    print(f"paper btc: {run.get('reason') or run['notes']}; {len(trades)} new trades -> {os.path.relpath(out, ROOT)}")
    for x in trades:
        print(f"  {x['side']:<4} {x['qty']} {x['ticker']} at {100 * x['price']:.0f}c (options {100 * x['p_opt']:.1f}c), "
              f"ties up ${x['capital']:.2f}")
    try:
        settle(extra={day: trades}, log="paper_btc", res="paper_btc_results")
    except Exception as e:
        print(f"paper btc: settlement check failed ({e}); will retry next run")


def all_trades(log="paper", res="paper_results"):
    """Every live trade on the data branch, by day, plus the settlement results recorded so far."""
    names = subprocess.run(["git", "ls-tree", "-r", "--name-only", "origin/data", f"data/raw/{log}/", f"data/raw/{res}/"],
                           cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    trades, results = {}, {}
    for n in sorted(names):
        if n.startswith(f"data/raw/{res}/"):
            results[os.path.basename(n)[:10]] = json.loads(subprocess.run(
                ["git", "show", f"origin/data:{n}"], cwd=ROOT, capture_output=True, check=True).stdout)
        else:
            trades.setdefault(n.split("/")[3], []).extend(r for r in L5.load(n) if r.get("type") == "trade")
    return trades, results


def settle(extra=None, log="paper", res="paper_results"):
    """Ask Kalshi for the result of every logged trade not yet settled; write data/raw/<res>/<day>.json."""
    sys.path.insert(0, os.path.join(ROOT, "collect"))
    from common import get_json
    BASE = "https://api.elections.kalshi.com/trade-api/v2"
    trades, results = all_trades(log, res)
    for d, ts in (extra or {}).items():
        trades.setdefault(d, []).extend(ts)
    for day, ts in trades.items():
        got = dict(results.get(day, {}))
        new = 0
        for tk in sorted({t["ticker"] for t in ts} - set(got)):
            m = get_json(f"{BASE}/markets/{tk}").get("market", {})
            if m.get("result") in ("yes", "no"):
                got[tk] = m["result"]; new += 1
        if new:
            d = os.path.join(RAW, res)
            os.makedirs(d, exist_ok=True)
            json.dump(got, open(os.path.join(d, f"{day}.json"), "w"), indent=0, sort_keys=True)
            print(f"paper: settled {new} trades from {day}")


def pnl_of(t, r):
    y = 1.0 if r == "yes" else 0.0
    return t["qty"] * ((y - t["price"]) if t["side"] == "buy" else (t["price"] - y)) - t["fee"]


def digest(days_back=1):
    """Plain-English list of the latest decisions and, where settled, whether each won: the last N stock trading days,
    and Bitcoin trades made in the last 24 hours times N."""
    subprocess.run(["git", "fetch", "-q", "origin", "+refs/heads/data:refs/remotes/origin/data"], cwd=ROOT, check=True)
    since = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=24 * days_back)
    for title, log, res in (("Stocks (S&P 500, Nasdaq-100 daily ranges)", "paper", "paper_results"),
                            ("Bitcoin (Kalshi hourly BTC)", "paper_btc", "paper_btc_results")):
        trades, results = all_trades(log, res)
        total, n_set, wins, rows = 0.0, 0, 0, []
        for day in sorted(trades):
            for t in sorted(trades[day], key=lambda t: t["snap"]):
                r = results.get(day, {}).get(t["ticker"])
                pnl = pnl_of(t, r) if r else None
                if r:
                    total += pnl; n_set += 1; wins += pnl > 0
                rows.append((day, t, r, pnl))
        if log == "paper":
            keep = set(sorted(trades)[-days_back:])
            show = [x for x in rows if x[0] in keep]
        else:
            show = [x for x in rows if pd.Timestamp(x[1]["snap"]) >= since]
        print(f"{title}:")
        for d, t, r, pnl in show:
            when = pd.Timestamp(t["snap"]).tz_convert("America/Vancouver").strftime("%a %H:%M")
            what = "bought YES" if t["side"] == "buy" else "sold YES"
            if log == "paper":
                name = L5.NAMES[t["series"]]
                rng_ = (f"{t['lo']:,.0f} to {t['hi']:,.0f}" if t["lo"] and t["hi"] else
                        f"above {t['lo']:,.0f}" if t["lo"] else f"below {t['hi']:,.0f}")
            else:
                name, rng_ = "BTC", f"above ${t['strike']:,.0f} ({t['kind']}, {t['hours_to_close']:.1f} h to settle)"
            out = "open" if r is None else f"{'WON' if pnl > 0 else 'LOST'} ${pnl:+.2f} (settled {r.upper()})"
            print(f"  {when} PT  {name:<10} {what} x{t['qty']} on {rng_} at {100 * t['price']:.0f}c "
                  f"(options said {100 * t['p_opt']:.1f}c) -> {out}")
        if not show:
            print("  no trades in this period")
        print(f"  Since live start: {sum(len(v) for v in trades.values())} trades, {n_set} settled, {wins} won, "
              f"{n_set - wins} lost, net ${total:+.2f} after fees")


def replay(check=False):
    files = L5.git_files()
    dec = []
    for day in sorted(files["kalshi"]):
        kept, last = [], -10 ** 9
        for k in sorted(files["kalshi"][day], key=L5.stamp_seconds):
            t = L5.stamp_seconds(k)
            if OPEN_S <= t <= CLOSE_S and t - last >= L5.MIN_GAP_S:
                kept.append(k); last = t
        traded = set()
        for k in kept:
            t = L5.stamp_seconds(k)
            opts = {}
            for series, (kind, _) in L5.PAIRS.items():
                near = min(files[kind].get(day, []), key=lambda o: abs(L5.stamp_seconds(o) - t), default=None)
                if near is not None and abs(L5.stamp_seconds(near) - t) <= L5.MAX_PAIR_S:
                    opts[series] = L5.load(near)
            sig, _ = signals(L5.load(k), opts, day)
            for s in sig:
                if s["ticker"] not in traded:
                    traded.add(s["ticker"]); dec.append(s)
    d = pd.DataFrame(dec)
    os.makedirs(OUT, exist_ok=True)
    d.to_csv(os.path.join(OUT, "replay_decisions.csv"), index=False)
    print(f"Replay {L5.START} to today: decisions only, no settlement.")
    for s, name in L5.NAMES.items():
        g = d[d.series == s] if len(d) else d
        if not len(g):
            print(f"  {name:<10} 0 trades"); continue
        cap = g.groupby("day").capital.sum()
        print(f"  {name:<10} {len(g)} trades on {g.day.nunique()} days ({(g.side == 'sell').sum()} sell, "
              f"{(g.side == 'buy').sum()} buy); capital tied up per day: median ${cap.median():,.0f}, max ${cap.max():,.0f}")
    if check:
        panel, _ = L5.build_panel()
        q = panel[panel.quoted & panel.covers].copy()
        q["y"] = 0.0                                     # outcome irrelevant: only which trades fire is compared
        ref = L5.trades(q, L5.THRESH)
        a = set(zip(ref.day, ref.ticker, ref.side, ref.price.round(4))) if len(ref) else set()
        b = set(zip(d.day, d.ticker, d.side, d.price.round(4))) if len(d) else set()
        print(f"  check against layer 5: {len(a)} vs {len(b)} trades, {len(a ^ b)} differ -> "
              f"{'MATCH' if a == b else 'MISMATCH'}")
        if a != b:
            sys.exit(1)


def report():
    if date.today() < L5.RUN_AFTER:
        sys.exit(f"Sealed until {L5.RUN_AFTER}, like layer 5. Use `replay` to see decisions (no profit) before then.")
    subprocess.run(["git", "fetch", "-q", "origin", "data"], cwd=ROOT, check=True)
    names = subprocess.run(["git", "ls-tree", "-r", "--name-only", "origin/data", "data/raw/paper/"],
                           cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    rows = [r for n in names if L5.START <= n.split("/")[3] <= L5.END for r in L5.load(n)]
    runs = [r for r in rows if r["type"] == "run"]
    t = pd.DataFrame([r for r in rows if r["type"] == "trade"])
    mk = []
    for s in L5.PAIRS:
        mk += [json.loads(l) for l in gzip.open(os.path.join(ROOT, "data", "history", "kalshi", f"markets_{s}.jsonl.gz"), "rt")]
    res = {m["ticker"]: {"yes": 1.0, "no": 0.0}.get(m.get("result")) for m in mk}
    lines = [f"Paper trading, live log {L5.START} to {L5.END}: {len(runs)} runs, "
             f"{sum(r.get('evaluated', False) for r in runs)} evaluated"]
    if not len(t):
        lines.append("  no trades"); print("\n".join(lines)); return
    t["y"] = t.ticker.map(res)
    lines.append(f"  trades without a settlement found: {int(t.y.isna().sum())}")
    t = t[t.y.notna()]
    sign = np.where(t.side == "buy", 1, -1)
    t["pnl"] = t.qty * (sign * (t.y - t.price)) - t.fee
    for s, name in L5.NAMES.items():
        g = t[t.series == s]
        if not len(g):
            lines.append(f"  {name:<10} no trades"); continue
        by = g.groupby("day").agg(pnl=("pnl", "sum"), cap=("capital", "sum"))
        lines.append(f"  {name:<10} {len(g)} trades on {len(by)} days: total ${g.pnl.sum():+,.2f}, "
                     f"{100 * g.pnl.sum() / g.qty.sum():+.2f}c per contract; win rate {(g.pnl > 0).mean():.0%}; "
                     f"worst day ${by.pnl.min():+,.2f}; most capital tied up in a day ${by.cap.max():,.2f}; "
                     f"return on peak capital {100 * by.pnl.sum() / by.cap.max():+.1f}%")
    txt = "\n".join(lines)
    print(txt)
    os.makedirs(OUT, exist_ok=True)
    t.to_csv(os.path.join(OUT, "live_trades_settled.csv"), index=False)
    open(os.path.join(OUT, "report.txt"), "w").write(txt + "\n")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "live":
        live_btc() if "--btc" in sys.argv else live()
    elif cmd == "replay":
        replay(check="--check" in sys.argv)
    elif cmd == "report":
        report()
    elif cmd == "digest":
        digest(int(sys.argv[2]) if len(sys.argv) > 2 else 1)
    else:
        sys.exit(__doc__)
