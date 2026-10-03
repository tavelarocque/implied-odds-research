"""Pull settled Kalshi markets and their price history.

Usage (run from the collect/ folder):
    python3 kalshi_history.py markets                 # settled market metadata + results, all series
    python3 kalshi_history.py candles --period 60     # hourly candles for every settled market
    python3 kalshi_history.py candles --period 1 --series KXINX --since 2026-09-01   # minute candles, a subset

Kalshi splits settled markets in two: recently settled ones come from /markets, and anything settled
before the archive cutoff comes from /historical/markets. Both are pulled and merged. Everything is
resumable: rerunning skips what's already on disk.
"""
import argparse, gzip, json, os, sys, time, urllib.parse
from datetime import datetime, timezone
from common import ROOT, get_json

BASE = "https://api.elections.kalshi.com/trade-api/v2"
SERIES = {
    "KXINX": "S&P 500 daily close range",
    "KXINXZ": "S&P 500 up on the day",
    "KXINXU": "S&P 500 above/below (hourly and daily)",
    "KXNASDAQ100": "Nasdaq-100 daily close range",
    "KXNASDAQ100Z": "Nasdaq-100 up on the day",
    "INX": "S&P 500 daily range (legacy ticker)",
    "INXZ": "S&P 500 up (legacy ticker)",
    "NASDAQ100": "Nasdaq-100 daily range (legacy ticker)",
}
HIST = os.path.join(ROOT, "data", "history", "kalshi")
DROP = {"rules_primary", "rules_secondary", "early_close_condition", "mve_selected_legs", "price_ranges"}
PAUSE = 0.08  # stay well under Kalshi's public rate limit


def paged(url, params, key="markets"):
    cursor = None
    while True:
        q = dict(params)
        if cursor:
            q["cursor"] = cursor
        page = get_json(f"{url}?{urllib.parse.urlencode(q)}")
        yield from page.get(key, [])
        cursor = page.get("cursor")
        time.sleep(PAUSE)
        if not cursor:
            return


def pull_markets(series_list):
    os.makedirs(HIST, exist_ok=True)
    for s in series_list:
        seen = {}
        for src, url, params in (
            ("live", f"{BASE}/markets", {"series_ticker": s, "status": "settled", "limit": 1000}),
            ("archive", f"{BASE}/historical/markets", {"series_ticker": s, "limit": 1000}),
        ):
            try:
                for m in paged(url, params):
                    r = {k: v for k, v in m.items() if k not in DROP}
                    r["_source"] = src
                    seen.setdefault(r["ticker"], r)
            except Exception as e:
                print(f"  {s} {src}: {e!r}", file=sys.stderr)
        rows = sorted(seen.values(), key=lambda r: r.get("close_time") or "")
        path = os.path.join(HIST, f"markets_{s}.jsonl.gz")
        with gzip.open(path, "wt", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, separators=(",", ":")) + "\n")
        events = {r["event_ticker"] for r in rows}
        span = f"{rows[0]['close_time'][:10]} to {rows[-1]['close_time'][:10]}" if rows else "none"
        print(f"{s:14} {len(rows):6} markets  {len(events):5} events  {span}  ({SERIES.get(s, '')})")


def load_markets(s):
    path = os.path.join(HIST, f"markets_{s}.jsonl.gz")
    if not os.path.exists(path):
        return []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(l) for l in f]


def ts(iso):
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def pull_candles(series_list, period, since=None, hours_before=None):
    """period in minutes: 1, 60 or 1440. hours_before limits the window before close (default: market lifetime)."""
    for s in series_list:
        outdir = os.path.join(HIST, f"candles_{period}m", s)
        os.makedirs(outdir, exist_ok=True)
        ms = [m for m in load_markets(s) if not since or (m.get("close_time") or "") >= since]
        done = fetched = failed = 0
        for m in ms:
            t = m["ticker"]
            path = os.path.join(outdir, f"{t}.json.gz")
            if os.path.exists(path):
                done += 1
                continue
            end = ts(m["close_time"])
            start = ts(m["open_time"]) if m.get("open_time") else end - 7 * 86400
            if hours_before:
                start = max(start, end - int(hours_before * 3600))
            q = urllib.parse.urlencode({"start_ts": start, "end_ts": end, "period_interval": period})
            urls = [f"{BASE}/series/{s}/markets/{t}/candlesticks?{q}", f"{BASE}/historical/markets/{t}/candlesticks?{q}"]
            if m.get("_source") == "archive":
                urls.reverse()
            candles = None
            for u in urls:
                try:
                    candles = get_json(u, retries=2).get("candlesticks", [])
                    break
                except Exception:
                    continue
            time.sleep(PAUSE)
            if candles is None:
                failed += 1
                continue
            with gzip.open(path, "wt", encoding="utf-8") as f:
                json.dump({"ticker": t, "period": period, "candlesticks": candles}, f, separators=(",", ":"))
            fetched += 1
            if fetched % 200 == 0:
                print(f"  {s}: {fetched} fetched, {done} already on disk, {failed} failed", flush=True)
        print(f"{s:14} candles {period}m: {fetched} fetched, {done} already on disk, {failed} failed")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["markets", "candles"])
    ap.add_argument("--series", nargs="*", default=list(SERIES))
    ap.add_argument("--period", type=int, default=60, choices=[1, 60, 1440])
    ap.add_argument("--since", help="only markets closing on/after this date, YYYY-MM-DD")
    ap.add_argument("--hours-before", type=float, help="only the last N hours before each market closes")
    a = ap.parse_args()
    if a.what == "markets":
        pull_markets(a.series)
    else:
        pull_candles(a.series, a.period, a.since, a.hours_before)
