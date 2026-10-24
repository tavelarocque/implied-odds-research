"""Live 15-minute Bitcoin up/down helper: tells you whether World's (Phantom's) price looks wrong, you press the button.

Nothing here touches a wallet. Each time you press Enter or type World's "Up" chance, it reads:
  - Kalshi's 15-minute BTC up/down market for the same window (KXBTC15M, public API; reading only, no trading),
  - Coinbase's live BTC price and the last hour of 1-minute candles,
and prints three probabilities for "Up": Kalshi's bid/ask, a fair value from the move so far, and World's (typed by you).

Fair value: P(up) = N( ln(S / K) / (sigma * sqrt(t_eff)) ). K is the window's start price (Kalshi's floor_strike: the
60-second average of CF Benchmarks' BRTI before the window opened), S is Coinbase's last trade, sigma is the realized
volatility of 1-minute log returns over the past hour, and t_eff = seconds left - 40, because Kalshi settles on a
60-second average (averaging removes about two-thirds of the last minute's variance). No drift.

Signal rule (fixed before any data, 2026-10-24; paper test first):
  BUY UP    if World's up price <= min(fair, Kalshi yes bid) - 0.04
  BUY DOWN  if World's up price >= max(fair, Kalshi yes ask) + 0.04
  No trade  if under 75 seconds left, Kalshi's spread is wider than 6 cents, or BTC is within $15 of the start price
            (World settles on Chainlink, Kalshi on BRTI; near the start price the two can disagree on the outcome).
  4 cents = about 3 cents measured entry cost on World (2026-10-24) + 1 cent buffer. Hold to the end of the window.

Every reading is logged to data/live15/readings.csv (git-ignored). The outcome is filled in from Kalshi's result once
the window settles (a proxy: World settles on Chainlink, which is almost always the same side away from the start).
Evaluation (written now): after at least 100 BUY signals on at least 7 days, the signals have an edge only if the
95% interval of profit per $1 share (outcome - price paid - 0.03) is above 0. Until then, paper or $0.05 only.

Run on the Mac (Kalshi blocks cloud machines):  python3 trade/live15.py
Commands: Enter = refresh | 62 = World shows Up 62% | s 81234.5 = override start price | t = mark last signal as
actually traded | r = report | q = quit
"""
import csv, json, math, os, statistics, sys, time, urllib.request
from datetime import datetime, timezone

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
COINBASE = "https://api.exchange.coinbase.com/products/BTC-USD"
THRESH, COST = 0.04, 0.03
MIN_LEFT_S, MAX_SPREAD, MIN_DIST = 75, 0.06, 15.0
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "data", "live15", "readings.csv")
FIELDS = ["ts_utc", "ticker", "close_utc", "secs_left", "start", "btc", "sigma_1m", "fair_up", "k_bid", "k_ask",
          "world_up", "signal", "edge", "traded", "result", "pnl_per_share"]


def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "implied-odds-live15", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=8) as r:
                return json.loads(r.read())
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(0.7 * (i + 1))


def utc(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def kalshi_window(now):
    # The live window has status "active" (the API's status=open filter misses it), so ask by close time instead.
    t0 = int(now.timestamp())
    ms = get(f"{KALSHI}/markets?series_ticker=KXBTC15M&min_close_ts={t0}&max_close_ts={t0 + 1800}&limit=10"
             ).get("markets", [])
    ms = [m for m in ms if m.get("status") in ("active", "open") and utc(m["close_time"]) > now]
    if not ms:
        return None
    m = min(ms, key=lambda m: utc(m["close_time"]))
    return {"ticker": m["ticker"], "close": utc(m["close_time"]), "open": utc(m["open_time"]),
            "start": num(m.get("floor_strike")), "bid": num(m.get("yes_bid_dollars")),
            "ask": num(m.get("yes_ask_dollars"))}


def btc_now_and_sigma():
    price = num(get(f"{COINBASE}/ticker")["price"])
    candles = get(f"{COINBASE}/candles?granularity=60")[:61]          # newest first: [time, low, high, open, close, vol]
    closes = [c[4] for c in reversed(candles)]
    rets = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]
    sigma = statistics.pstdev(rets) if len(rets) > 10 else 0.0006      # per-minute log-return volatility
    return price, max(sigma, 0.0002)


def read_log():
    if not os.path.exists(LOG):
        return []
    with open(LOG, newline="") as f:
        return list(csv.DictReader(f))


def write_log(rows):
    if os.path.dirname(LOG):
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
    tmp = LOG + ".tmp"
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, LOG)


def resolve(rows, now):
    """Fill in Kalshi's result for windows that ended more than 6 minutes ago."""
    changed, cache = False, {}
    for r in rows:
        if r["result"] or (now - utc(r["close_utc"])).total_seconds() < 360:
            continue
        t = r["ticker"]
        if t not in cache:
            try:
                cache[t] = get(f"{KALSHI}/markets/{t}").get("market", {}).get("result")
            except Exception:
                cache[t] = None
        res = cache[t]
        if res in ("yes", "no"):
            r["result"] = "up" if res == "yes" else "down"
            if r["signal"] in ("BUY UP", "BUY DOWN"):
                w = float(r["world_up"])
                won = (r["signal"] == "BUY UP") == (r["result"] == "up")
                price = w if r["signal"] == "BUY UP" else 1 - w
                r["pnl_per_share"] = f"{(1.0 if won else 0.0) - price - COST:+.4f}"
            changed = True
    return changed


def decide(world, fair, kb, ka, secs_left, dist):
    if secs_left < MIN_LEFT_S:
        return "NO TRADE (too late)", 0.0
    if kb is None or ka is None or ka - kb > MAX_SPREAD:
        return "NO TRADE (Kalshi quote stale/wide)", 0.0
    if dist < MIN_DIST:
        return "NO TRADE (too close to start price)", 0.0
    lo, hi = min(fair, kb), max(fair, ka)
    if world <= lo - THRESH:
        return "BUY UP", lo - world
    if world >= hi + THRESH:
        return "BUY DOWN", world - hi
    return "NO TRADE", max(lo - world, world - hi)


def report(rows):
    sig = [r for r in rows if r["signal"] in ("BUY UP", "BUY DOWN")]
    done = [r for r in sig if r["pnl_per_share"]]
    days = {r["ts_utc"][:10] for r in sig}
    print(f"\n  readings {len(rows)} | signals {len(sig)} on {len(days)} days | settled {len(done)} | "
          f"marked traded {sum(r['traded'] == 'y' for r in sig)}")
    if done:
        p = [float(r["pnl_per_share"]) for r in done]
        wins = sum(x > 0 for x in p)
        mean = statistics.mean(p)
        se = statistics.stdev(p) / math.sqrt(len(p)) if len(p) > 1 else float("nan")
        print(f"  signals won {wins}/{len(p)} | mean profit per $1 share {mean:+.3f} "
              f"(rough 95%: {mean - 1.96 * se:+.3f} to {mean + 1.96 * se:+.3f}) after {COST:.2f} cost")
    scored = [r for r in rows if r["result"] and r["world_up"]]
    if scored:
        def brier(key):
            return statistics.mean((float(r[key]) - (r["result"] == "up")) ** 2 for r in scored)
        kb = [r for r in scored if r["k_bid"] and r["k_ask"]]
        km = statistics.mean(((float(r["k_bid"]) + float(r["k_ask"])) / 2 - (r["result"] == "up")) ** 2 for r in kb) \
            if kb else float("nan")
        print(f"  Brier on {len(scored)} settled readings (lower is better): World {brier('world_up'):.4f} | "
              f"Kalshi mid {km:.4f} | fair {brier('fair_up'):.4f}")
    print(f"  verdict rule: edge only with 100+ signals on 7+ days and the interval above 0\n")


def main():
    rows = read_log()
    start_override, last = None, None
    print(__doc__.split("\n\n")[0])
    print("Commands: Enter = refresh | 62 = World shows Up 62% | s 81234.5 = override start | t = traded | r | q\n")
    while True:
        try:
            cmd = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break
        if cmd == "q":
            break
        if cmd == "r":
            report(rows)
            continue
        if cmd == "t":
            if last is not None and last["signal"] in ("BUY UP", "BUY DOWN"):
                last["traded"] = "y"
                write_log(rows)
                print("  marked as traded")
            else:
                print("  no signal to mark")
            continue
        if cmd.startswith("s "):
            v = num(cmd[2:])
            start_override = (v, None) if v else None
            print(f"  start price override: {v} (this window only)")
            continue
        world = None
        if cmd:
            w = num(cmd.rstrip("%"))
            if w is None or not 0 < w < 100:
                print("  type World's Up chance as a number between 1 and 99, e.g. 62")
                continue
            world = w / 100
        now = datetime.now(timezone.utc)
        try:
            k = kalshi_window(now)
            btc, sigma = btc_now_and_sigma()
        except Exception as e:
            print(f"  data error: {e!r}")
            continue
        if k is None:
            print("  no open KXBTC15M window found")
            continue
        if start_override and start_override[1] is None:
            start_override = (start_override[0], k["ticker"])      # an override applies to the window it was set in
        if start_override and start_override[1] != k["ticker"]:
            start_override = None
        start = start_override[0] if start_override else k["start"]
        if not start:
            print("  Kalshi gave no start price for this window; set one with  s <price>")
            continue
        secs_left = (k["close"] - now).total_seconds()
        t_eff = max(secs_left - 40, 1) / 60
        fair = phi(math.log(btc / start) / (sigma * math.sqrt(t_eff)))
        local = k["close"].astimezone().strftime("%H:%M")
        print(f"  window ends {local} | {int(secs_left // 60)}m{int(secs_left % 60):02d}s left | start ${start:,.2f} | "
              f"BTC ${btc:,.2f} ({btc - start:+,.0f}) | 1-min vol {sigma * 100:.3f}%")
        kb, ka = k["bid"], k["ask"]
        print(f"  Up chance:  fair {fair * 100:5.1f}%  |  Kalshi {kb * 100 if kb else float('nan'):4.0f}-"
              f"{ka * 100 if ka else float('nan'):.0f}%" + (f"  |  World {world * 100:.0f}%" if world else ""))
        if world is None:
            continue
        signal, edge = decide(world, fair, kb, ka, secs_left, abs(btc - start))
        flag = ">>> " if signal.startswith("BUY") else "    "
        print(f"{flag}{signal}" + (f"   (World off by {edge * 100:.0f}c; hold to the end of the window)"
                                   if signal.startswith("BUY") else ""))
        last = {"ts_utc": now.isoformat(timespec="seconds"), "ticker": k["ticker"], "close_utc": k["close"].isoformat(),
                "secs_left": f"{secs_left:.0f}", "start": f"{start:.2f}", "btc": f"{btc:.2f}",
                "sigma_1m": f"{sigma:.6f}", "fair_up": f"{fair:.4f}", "k_bid": "" if kb is None else f"{kb:.2f}",
                "k_ask": "" if ka is None else f"{ka:.2f}", "world_up": f"{world:.2f}", "signal": signal,
                "edge": f"{edge:.3f}", "traded": "", "result": "", "pnl_per_share": ""}
        rows.append(last)
        resolve(rows, now)
        write_log(rows)
    if resolve(rows, datetime.now(timezone.utc)):
        write_log(rows)
    report(rows)


if __name__ == "__main__":
    main()
