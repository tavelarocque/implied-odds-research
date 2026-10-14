"""Layer 5x (research/PREREGISTRATION_LAYER5X.md): would layer 5's Bitcoin paper trades have filled? No money, no keys.

Two measurements on every layer 5 BTC paper trade, both from Kalshi's public endpoints:
  (A) requote: seconds after the paper decision (when a real order would land), re-read the full order book and record
      how many contracts were still available at the paper price or better. An immediate-or-cancel order for N contracts
      at the paper price fills min(N, available). Logged as "requote" rows, live only (cannot be backfilled).
  (B) prints: 10+ minutes later, pull the public trade prints on that contract around the snapshot and classify whether
      anyone actually traded in our direction at our price or better within 120 s. Logged as "prints" rows; runs over
      past trades too (backfill), a capped number per run.
Logs to data/raw/exec_check/<day>/. Never touches the paper trader's own logs or decisions.
"""
import glob, gzip, json, math, os, subprocess, sys, time, urllib.error, urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
BASE = "https://api.elections.kalshi.com/trade-api/v2"
SIZES = (2, 10, 100)
CONFIRM_S, WIDE_S, PRE_S = 120, 600, 300      # print windows after / before the snapshot, seconds
MIN_AGE_S = 900                               # wait until the wide window is complete before pulling prints
MAX_PRINTS_PER_RUN = 60
UA = {"User-Agent": "implied-odds-research/1.0"}


def _get(path, timeout=15):
    """One public GET; backs off and retries on Kalshi's rate limit (429)."""
    for attempt in range(4):
        req = urllib.request.Request(BASE + path, headers=UA)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 3:
                return e.code, {}
            time.sleep(1.5 * (attempt + 1))


def fee(price, n):
    """Kalshi taker fee, rounded up to the cent per order (same formula as layer 5's 100-lot fee)."""
    return math.ceil(round(0.07 * price * (1 - price) * n * 100, 6)) / 100 if n > 0 else 0.0


def book_levels(ob):
    """(yes_bids, yes_asks) as [(price, size)], best first, from either orderbook format."""
    if "orderbook_fp" in ob:
        y = [(float(p), float(s)) for p, s in ob["orderbook_fp"].get("yes_dollars") or []]
        n = [(float(p), float(s)) for p, s in ob["orderbook_fp"].get("no_dollars") or []]
    else:
        o = ob.get("orderbook") or {}
        y = [(p / 100, float(s)) for p, s in o.get("yes") or []]
        n = [(p / 100, float(s)) for p, s in o.get("no") or []]
    bids = sorted(y, key=lambda x: -x[0])
    asks = sorted(((round(1 - p, 4), s) for p, s in n), key=lambda x: x[0])
    return bids, asks


def available(t, bids, asks):
    """Contracts an IOC limit order at the paper price would reach: asks <= price for a buy, bids >= price for a sell."""
    p = t["price"]
    if t["side"] == "buy":
        return sum(s for q, s in asks if q <= p + 1e-9), (asks[0] if asks else (None, 0.0))
    return sum(s for q, s in bids if q >= p - 1e-9), (bids[0] if bids else (None, 0.0))


def requote(t):
    st, ob = _get(f"/markets/{t['ticker']}/orderbook")
    src = "orderbook"
    if st == 200 and ob:
        bids, asks = book_levels(ob)
    else:                                       # fall back to the public market touch (no depth beyond best price)
        src = f"market (orderbook status {st})"
        st2, m = _get(f"/markets/{t['ticker']}")
        m = m.get("market", {})
        if st2 != 200 or not m:
            return {"source": f"failed (orderbook {st}, market {st2})"}
        b, a = float(m.get("yes_bid_dollars") or 0), float(m.get("yes_ask_dollars") or 0)
        bs, as_ = float(m.get("yes_bid_size_fp") or 0), float(m.get("yes_ask_size_fp") or 0)
        bids = [(b, bs)] if bs > 0 else []
        asks = [(a, as_)] if as_ > 0 and a < 1 else []
    avail, best = available(t, bids, asks)
    return {"source": src, "available": avail, "best_price": best[0], "best_size": best[1],
            "fills": {str(n): min(n, avail) for n in SIZES}}


def live(paper_trades, kpath, now):
    """(A): called right after the paper trader writes its trades, before anything else slow runs."""
    if not paper_trades:
        return
    rows = []
    for t in paper_trades:
        r = {"type": "requote", "ticker": t["ticker"], "day": t["day"], "snap": t["snap"], "side": t["side"],
             "price": t["price"], "kind": t.get("kind"), "hours_to_close": t.get("hours_to_close"),
             "paper_size_shown": t["ask_size"] if t["side"] == "buy" else t["bid_size"], "decided_utc": now.isoformat()}
        try:
            r.update(requote(t))
        except Exception as e:
            r["source"] = f"failed ({str(e)[:200]})"
        r["requoted_utc"] = datetime.now(timezone.utc).isoformat()
        r["latency_s"] = round((datetime.fromisoformat(r["requoted_utc"]) - datetime.fromisoformat(t["snap"])).total_seconds(), 1)
        rows.append(r)
    _write(rows, now, kpath)
    ok = [r for r in rows if "available" in r]
    full = sum(1 for r in ok if r["available"] >= 100)
    print(f"exec check: requoted {len(ok)}/{len(rows)} trades, {full} still had 100+ at the paper price "
          f"(median {sorted(r['latency_s'] for r in rows)[len(rows) // 2]:.0f} s after the snapshot)")


def _ours(t, p):
    """Does public print p show a taker trading in our direction at our price or better?"""
    side = p.get("taker_outcome_side") or p.get("taker_side")
    y = float(p.get("yes_price_dollars") or (p.get("yes_price", 0) / 100))
    if t["side"] == "buy":
        return side == "yes", y <= t["price"] + 1e-9
    return side == "no", y >= t["price"] - 1e-9


def prints_for(t):
    s = datetime.fromisoformat(t["snap"]).timestamp()
    out, cursor = [], ""
    for _ in range(5):
        st, js = _get(f"/markets/trades?ticker={t['ticker']}&min_ts={int(s - PRE_S)}&max_ts={int(s + WIDE_S)}"
                      f"&limit=1000&is_block_trade=false" + (f"&cursor={cursor}" if cursor else ""))
        if st != 200:
            return None, st
        out += js.get("trades") or []
        cursor = js.get("cursor") or ""
        if not cursor:
            break
    r = {"n_prints": len(out), "ours_at_or_better_120": 0.0, "ours_worse_120": 0.0, "ours_at_or_better_600": 0.0,
         "any_120": 0.0, "pre_last_yes_price": None}
    pre = []
    for p in out:
        ts = datetime.fromisoformat(p["created_time"].replace("Z", "+00:00")).timestamp() - s
        c = float(p.get("count_fp") or p.get("count") or 0)
        ours, good = _ours(t, p)
        if ts <= 0:
            pre.append((ts, float(p.get("yes_price_dollars") or 0)))
            continue
        if ts <= CONFIRM_S:
            r["any_120"] += c
            if ours:
                r["ours_at_or_better_120" if good else "ours_worse_120"] += c
        if ours and good and ts <= WIDE_S:
            r["ours_at_or_better_600"] += c
    if pre:
        r["pre_last_yes_price"] = max(pre)[1]
    r["class"] = ("confirmed" if r["ours_at_or_better_120"] > 0 else "moved" if r["ours_worse_120"] > 0 else "quiet")
    return r, 200


def _done(kind):
    names = subprocess.run(["git", "ls-tree", "-r", "--name-only", "origin/data", "data/raw/exec_check/"],
                           cwd=ROOT, capture_output=True, text=True).stdout.split()
    sys.path.insert(0, os.path.join(ROOT, "research"))
    import options_vs_kalshi as L5
    rows = [r for n in names for r in L5.load(n)]
    return rows, {(r["ticker"], r["snap"]) for r in rows if r.get("type") == kind}


def prints_pass(now, kpath):
    """(B): pull prints for paper trades at least 15 minutes old that have none yet, oldest first, capped per run."""
    import paper as P
    trades, _ = P.all_trades("paper_btc", "paper_btc_results")
    _, done = _done("prints")
    todo = sorted((t for ts in trades.values() for t in ts
                   if (t["ticker"], t["snap"]) not in done
                   and now.timestamp() - datetime.fromisoformat(t["snap"]).timestamp() >= MIN_AGE_S),
                  key=lambda t: t["snap"])[:MAX_PRINTS_PER_RUN]
    rows = []
    for t in todo:
        time.sleep(0.4)                         # stay under Kalshi's public rate limit
        r, st = prints_for(t)
        base = {"type": "prints", "ticker": t["ticker"], "day": t["day"], "snap": t["snap"], "side": t["side"],
                "price": t["price"], "kind": t.get("kind")}
        rows.append({**base, **r} if r else {**base, "type": "prints_error", "status": st})
    if rows:
        _write(rows, now, kpath, tag="prints")
        cls = [r.get("class") for r in rows if r["type"] == "prints"]
        print(f"exec check: prints for {len(rows)} trades: " +
              ", ".join(f"{c} {cls.count(c)}" for c in ("confirmed", "moved", "quiet")) +
              (f", {len(rows) - len(cls)} errors" if len(cls) < len(rows) else ""))


def _write(rows, now, kpath, tag="requote"):
    day = now.strftime("%Y-%m-%d")
    d = os.path.join(RAW, "exec_check", day)
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, f"exec_check_{tag}_{os.path.basename(kpath).split('_')[-1]}")
    with gzip.open(out, "at") as f:
        for r in rows:
            f.write(json.dumps(r, default=str) + "\n")


def report():
    """Running numbers for the registered readout: fill rates, execution-adjusted P&L, selection check, print classes."""
    import paper as P
    rows, _ = _done("requote")
    trades, results = P.all_trades("paper_btc", "paper_btc_results")
    res = {(t["ticker"], t["snap"]): results.get(d, {}).get(t["ticker"]) for d, ts in trades.items() for t in ts}
    paper = {(t["ticker"], t["snap"]): t for ts in trades.values() for t in ts}
    rq = [r for r in rows if r["type"] == "requote" and "available" in r and res.get((r["ticker"], r["snap"]))]
    print(f"requoted and settled: {len(rq)}")
    if rq:
        for n in SIZES:
            fills = [min(n, r["available"]) for r in rq]
            pp = ex = 0.0
            for r, f in zip(rq, fills):
                t, y = paper[(r["ticker"], r["snap"])], 1.0 if res[(r["ticker"], r["snap"])] == "yes" else 0.0
                edge = (y - t["price"]) if t["side"] == "buy" else (t["price"] - y)
                pp += n * edge - fee(t["price"], n)
                ex += f * edge - fee(t["price"], f)
            print(f"  N={n:>3}: full fills {sum(f >= n for f in fills)}/{len(rq)}, contracts {sum(fills):.0f}/{n * len(rq)}, "
                  f"paper P&L ${pp:,.2f}, execution-adjusted ${ex:,.2f}, ratio " + (f"{ex / pp:.2f}" if pp > 0 else "n/a (paper P&L not positive)"))
    pr = [r for r in rows if r["type"] == "prints"]
    for c in ("confirmed", "moved", "quiet"):
        g = [r for r in pr if r["class"] == c]
        s = [P.pnl_of(paper[(r["ticker"], r["snap"])], res[(r["ticker"], r["snap"])]) for r in g
             if res.get((r["ticker"], r["snap"])) and (r["ticker"], r["snap"]) in paper]
        print(f"  prints {c:<9}: {len(g):>4} trades, settled paper P&L ${sum(s):,.2f}")


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    if sys.argv[1:] == ["report"]:
        subprocess.run(["git", "fetch", "-q", "origin", "+refs/heads/data:refs/remotes/origin/data"], cwd=ROOT)
        report()
