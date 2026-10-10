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
    python3 trade/paper.py live --btc      the same for Bitcoin (research/PREREGISTRATION_BTC.md; crypto workflow), then
                                           layer 11's rule (research/PREREGISTRATION_LAYER11.md, test B) when the
                                           snapshot is 2.5-3.5 h before the 5pm ET set settles
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
    try:
        live_l11(krows, kpath, now)
        settle(log="paper_l11", res="paper_l11_results")
        settle_maker()
    except Exception as e:                                  # never let layer 11 break the layer 5 paper trader
        print(f"paper l11: failed ({e})")


L11_FG, L11_FUNDING, L11_H, L11_TOL_H = 25, 0.0000149, 3.0, 0.5


def l11_mood(close):
    """Layer 11's two signals as known at decision time (research/PREREGISTRATION_LAYER11.md). Either can be None if
    its source is unreachable; the forward test itself is computed afterwards from the histories."""
    sys.path.insert(0, os.path.join(ROOT, "collect"))
    from common import get_json
    fg = None
    try:
        for x in get_json("https://api.alternative.me/fng/?limit=3&format=json")["data"]:
            if datetime.fromtimestamp(int(x["timestamp"]), timezone.utc).strftime("%Y-%m-%d") == close.strftime("%Y-%m-%d"):
                fg = int(x["value"])
    except Exception:
        pass
    funding = None
    try:
        end = close - pd.Timedelta(hours=6)
        page = get_json("https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&startTime="
                        f"{int((end - pd.Timedelta(hours=30)).timestamp() * 1000)}&limit=20", retries=2)
        r = [float(p["fundingRate"]) for p in page
             if end - pd.Timedelta(hours=24) < pd.Timestamp(p["fundingTime"], unit="ms", tz="UTC") <= end]
        funding = float(np.mean(r)) if r else None
    except Exception:
        pass
    return fg, funding


def live_l11(krows, kpath, now):
    """Layer 11 live (test B): on a bearish-mood day, at the one snapshot 2.5 to 3.5 hours before the 5pm ET Bitcoin
    set settles, buy YES at the ask on every contract with mid >= 90c and spread <= 10c (selling the downside long
    shot). One evaluation per set. Logs to data/raw/paper_l11/, results to data/raw/paper_l11_results/."""
    collected = L5.utc(krows[0]["collected_utc"])
    ms = [m for m in krows if m.get("type") == "market" and m.get("series") == "KXBTCD"
          and m["event_ticker"].endswith("17") and m.get("strike_type") == "greater"]
    ms = [m for m in ms if abs((L5.utc(m["close_time"]) - collected).total_seconds() / 3600 - L11_H) <= L11_TOL_H]
    if not ms:
        return
    ms = [m for m in ms if m["event_ticker"] == ms[0]["event_ticker"]]
    close = L5.utc(ms[0]["close_time"])
    h = (close - collected).total_seconds() / 3600
    day = close.strftime("%Y-%m-%d")
    if any(rows and rows[0].get("evaluated") for _, rows in logged_runs(day, "paper_l11")):
        print("paper l11: this set was already evaluated"); return
    fg, funding = l11_mood(close)
    signal = (fg is not None and fg <= L11_FG) or (funding is not None and funding <= L11_FUNDING)
    run = {"type": "run", "day": day, "event": ms[0]["event_ticker"], "snap": krows[0]["collected_utc"],
           "decided_utc": now.isoformat(), "hours_to_close": h, "commit": os.environ.get("GITHUB_SHA", "local"),
           "evaluated": True, "fear_greed": fg, "funding": funding, "signal": bool(signal)}
    trades = []
    if signal:
        for m in ms:
            bid, ask, bsz, asz = L5.kalshi_quote(m)
            if not (bid > 0 and ask is not None and ask < 1 and ask - bid <= 0.10 and (bid + ask) / 2 >= 0.90):
                continue
            trades.append(sized({"type": "trade", "series": "KXBTCD", "rule": "layer11", "day": day,
                                 "snap": run["snap"], "event": m["event_ticker"], "ticker": m["ticker"],
                                 "strike": float(m["floor_strike"]), "bid": bid, "ask": ask, "bid_size": bsz,
                                 "ask_size": asz, "hours_to_close": h, "side": "buy", "price": float(ask)}))
    run["new_trades"] = len(trades)
    # Shadow maker version (logged only, never traded; Burgi, Deng & Whelan 2026: makers do far better than takers):
    # instead of buying YES at the ask, rest a bid at the current YES bid, 100 contracts, until settlement. Filled
    # only if later trades show it would have been (checked after settlement by settle_maker). Kalshi's fee schedule
    # (effective 2026-07-07) charges makers only on listed series; KXBTCD is not listed, so the maker fee is 0.
    makers = [{"type": "maker", "series": "KXBTCD", "rule": "layer11-maker-shadow", "day": day, "snap": run["snap"],
               "placed_utc": krows[0]["collected_utc"], "event": t["event"], "ticker": t["ticker"],
               "strike": t["strike"], "price": t["bid"], "ask": t["ask"], "bid_size_ahead": t["bid_size"],
               "qty": QTY, "fee": 0.0, "hours_to_close": h} for t in trades]
    d = os.path.join(RAW, "paper_l11", day)
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, f"paper_l11_{os.path.basename(kpath).split('_')[-1]}")
    with gzip.open(out, "wt") as f:
        for r in [run] + trades + makers:
            f.write(json.dumps(r) + "\n")
    print(f"paper l11: F&G {fg}, funding {funding}; signal {'YES' if signal else 'no'}; {len(trades)} trades "
          f"-> {os.path.relpath(out, ROOT)}")
    for x in trades:
        print(f"  buy {x['qty']} YES {x['ticker']} at {100 * x['price']:.0f}c, ties up ${x['capital']:.2f}")


def settle_maker():
    """For each shadow maker bid whose market has settled: the result, and whether it would have filled. A trade
    printed below the bid means the price went through it (filled for sure, 'through'); a trade at the bid means it may
    have filled, depending on queue position ('touch'). Writes data/raw/paper_l11_maker/<day>.json."""
    sys.path.insert(0, os.path.join(ROOT, "collect"))
    from common import get_json
    BASE = "https://api.elections.kalshi.com/trade-api/v2"
    names = subprocess.run(["git", "ls-tree", "-r", "--name-only", "origin/data", "data/raw/paper_l11/",
                            "data/raw/paper_l11_maker/"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    done, rows = {}, {}
    for n in names:
        if n.startswith("data/raw/paper_l11_maker/"):
            done[os.path.basename(n)[:10]] = json.loads(subprocess.run(["git", "show", f"origin/data:{n}"], cwd=ROOT,
                                                                       capture_output=True, check=True).stdout)
        else:
            for r in L5.load(n):
                if r.get("type") == "maker":
                    rows.setdefault(r["day"], []).append(r)
    for day, ms in rows.items():
        got, new = dict(done.get(day, {})), 0
        for m in ms:
            if m["ticker"] in got:
                continue
            mk = get_json(f"{BASE}/markets/{m['ticker']}").get("market", {})
            if mk.get("result") not in ("yes", "no"):
                continue
            lo, cursor, t0 = None, None, int(pd.Timestamp(m["placed_utc"]).timestamp())
            t1 = int(pd.Timestamp(mk["close_time"]).timestamp())
            while True:
                q = f"{BASE}/markets/trades?ticker={m['ticker']}&min_ts={t0}&max_ts={t1}&limit=1000" + (f"&cursor={cursor}" if cursor else "")
                page = get_json(q)
                for tr in page.get("trades", []):
                    p = tr.get("yes_price_dollars", tr.get("yes_price"))
                    p = float(p) if isinstance(p, str) else (p / 100 if p is not None else None)
                    if p is not None:
                        lo = p if lo is None else min(lo, p)
                cursor = page.get("cursor")
                if not cursor:
                    break
            got[m["ticker"]] = {"result": mk["result"], "min_trade": lo,
                                "fill_through": lo is not None and lo < m["price"] - 1e-9,
                                "fill_touch": lo is not None and lo <= m["price"] + 1e-9}
            new += 1
        if new:
            d = os.path.join(RAW, "paper_l11_maker")
            os.makedirs(d, exist_ok=True)
            json.dump(got, open(os.path.join(d, f"{day}.json"), "w"), indent=0, sort_keys=True)
            print(f"paper l11 maker: settled {new} shadow bids from {day}")


def maker_summary():
    """Digest lines for the shadow maker log: fills and what they would have earned (fee 0 on KXBTCD)."""
    names = subprocess.run(["git", "ls-tree", "-r", "--name-only", "origin/data", "data/raw/paper_l11/",
                            "data/raw/paper_l11_maker/"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    res, rows = {}, []
    for n in names:
        if n.startswith("data/raw/paper_l11_maker/"):
            res.update(json.loads(subprocess.run(["git", "show", f"origin/data:{n}"], cwd=ROOT, capture_output=True,
                                                 check=True).stdout))
        else:
            rows += [r for r in L5.load(n) if r.get("type") == "maker"]
    if not rows:
        return ["  shadow maker (limit-order) version: no bids yet"]
    settled = [(r, res[r["ticker"]]) for r in rows if r["ticker"] in res]
    out = [f"  shadow maker version: {len(rows)} bids logged, {len(settled)} settled"]
    for kind in ("fill_through", "fill_touch"):
        f = [(r, s) for r, s in settled if s[kind]]
        pnl = sum(r["qty"] * ((1.0 if s["result"] == "yes" else 0.0) - r["price"]) for r, s in f)
        out.append(f"    if filled only when traded {'through' if kind == 'fill_through' else 'at or through'} the bid: "
                   f"{len(f)} fills, {sum(s['result'] == 'no' for _, s in f)} lost, net ${pnl:+.2f}")
    return out


def drift_monitor(alpha=0.2, gamma=0.05, window=20):
    """Drift alarm for the options model behind layer 5's paper trades (stocks and Bitcoin), in settlement order.

    1. Adaptive conformal inference (Gibbs & Candes 2021): score s = |y - p_opt|; the model 'covers' a trade if s is
       within the (1 - alpha_t) quantile of earlier scores; alpha_{t+1} = alpha_t + gamma (alpha - err_t). If recent
       misses run well above alpha, the model's errors have grown: the alarm. gamma is 0.05 rather than the paper's
       0.005 because trades arrive by the dozen, not the thousand.
    2. On the same settled trades: Brier score of the options probability vs Kalshi's mid. Layer 5 trades only where
       the two disagree by 3+ cents, so this is the live answer to "who was right when they disagreed".
    Monitoring only: changes no trade and no pre-registered analysis."""
    rows = []
    for log, res in (("paper", "paper_results"), ("paper_btc", "paper_btc_results")):
        trades, results = all_trades(log, res)
        for day, ts_ in trades.items():
            for t in ts_:
                r = results.get(day, {}).get(t["ticker"])
                if r not in ("yes", "no"):
                    continue
                settle_t = pd.Timestamp(t["snap"]) + pd.Timedelta(hours=float(t.get("hours_to_close", 0)))
                rows.append((settle_t, float(t["p_opt"]), (t["bid"] + t["ask"]) / 2, 1.0 if r == "yes" else 0.0))
    if len(rows) < 5:
        return [f"  drift alarm: {len(rows)} settled trades so far; starts at 5"]
    rows.sort(key=lambda r: r[0])
    p, mid, y = (np.array([r[i] for r in rows]) for i in (1, 2, 3))
    s = np.abs(y - p)
    a, errs = alpha, []
    for i in range(len(s)):
        prev = s[:i]
        q = np.inf if (a <= 0 or len(prev) == 0) else (-np.inf if a >= 1 else np.quantile(prev, 1 - a))
        e = float(s[i] > q); errs.append(e)
        a += gamma * (alpha - e)
    recent = np.array(errs[-window:])
    band = alpha + 2 * np.sqrt(alpha * (1 - alpha) / len(recent))
    alarm = len(recent) >= 10 and recent.mean() > band
    b_opt, b_mid = ((p - y) ** 2).mean(), ((mid - y) ** 2).mean()
    note = "; too few trades to judge before ~30" if len(rows) < 30 else ""
    return [f"  drift alarm ({len(rows)} settled layer 5 trades, stocks + Bitcoin): recent misses "
            f"{recent.mean():.0%} of the last {len(recent)} vs target {alpha:.0%} (alarm above {band:.0%}) -> "
            f"{'ALARM: the options model is missing more than it should' if alarm else 'ok'}",
            f"  who was right when they disagreed: Brier options {b_opt:.3f} vs Kalshi mid {b_mid:.3f} "
            f"({'options better' if b_opt < b_mid else 'Kalshi better'}; lower is better{note})"]


def l11_runs():
    names = subprocess.run(["git", "ls-tree", "-r", "--name-only", "origin/data", "data/raw/paper_l11/"],
                           cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    return [L5.load(n)[0] for n in sorted(names)]


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
                            ("Bitcoin (Kalshi hourly BTC)", "paper_btc", "paper_btc_results"),
                            ("Bitcoin layer 11 (sell downside long shots on fear days, 3 h before 5pm ET)",
                             "paper_l11", "paper_l11_results")):
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
            elif log == "paper_btc":
                name, rng_ = "BTC", f"above ${t['strike']:,.0f} ({t['kind']}, {t['hours_to_close']:.1f} h to settle)"
            else:
                name, rng_ = "BTC L11", f"above ${t['strike']:,.0f} ({t['hours_to_close']:.1f} h to settle)"
            out = "open" if r is None else f"{'WON' if pnl > 0 else 'LOST'} ${pnl:+.2f} (settled {r.upper()})"
            why = f"(options said {100 * t['p_opt']:.1f}c)" if "p_opt" in t else "(selling the long shot)"
            print(f"  {when} PT  {name:<10} {what} x{t['qty']} on {rng_} at {100 * t['price']:.0f}c {why} -> {out}")
        if log == "paper_l11":
            try:
                print("\n".join(maker_summary()))
            except Exception as e:
                print(f"  shadow maker summary unavailable ({e})")
            for run in l11_runs():
                if pd.Timestamp(run["snap"]) >= since:
                    print(f"  {run['day']}: Fear & Greed {run['fear_greed']}, funding {run['funding']}; "
                          f"signal {'YES' if run['signal'] else 'no'}, {run['new_trades']} trades")
        if not show:
            print("  no trades in this period")
        print(f"  Since live start: {sum(len(v) for v in trades.values())} trades, {n_set} settled, {wins} won, "
              f"{n_set - wins} lost, net ${total:+.2f} after fees")
    print("Model health:")
    try:
        print("\n".join(drift_monitor()))
    except Exception as e:
        print(f"  drift alarm unavailable ({e})")


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
