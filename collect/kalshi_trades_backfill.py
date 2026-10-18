"""Backfill, after settlement, every Kalshi KXBTCD trade print near the money, and Coinbase 1-minute BTC prices.

Layer 16's markout needs each trade and the BTC price in the seconds and minutes after it. Both can be fetched after
the fact: Kalshi keeps a market's full trade history (checked 2026-10-17: a settled daily market returned all 11,767
trades of its week), and Kraken serves every XBT/USD trade, from which the last price each second follows. Coinbase's
1-minute candles, also kept, are too coarse for a 60-second markout: a price up to a minute old shifts a last-hour
digital by about a cent on average (test_markout in the contracts project), so they are only used to choose strikes. So this needs no machine that stays awake. Run it
weekly (Kalshi's archive policy for old trades is not documented, so don't leave it months):

    python3 kalshi_trades_backfill.py                       events that closed in the last 8 days
    python3 kalshi_trades_backfill.py --since 2026-10-17    events that closed on or after a date

Writes, resumably:
  data/history/kalshi/trades/KXBTCD/<event>.jsonl.gz   a 'market' row per market kept, then its 'trade' rows
  data/history/crypto/coinbase_1m_days/<YYYY-MM-DD>.json   Coinbase BTC-USD 1-minute candles for one UTC day,
                                                           [start, low, high, open, close, volume]
  data/history/crypto/kraken_1s/<YYYY-MM-DD>.json.gz        Kraken XBT/USD last trade price each second with a
                                                           trade, [unix_second, price], one UTC day
Markets kept: KXBTCD "above" contracts whose strike is within 2% of the Coinbase price one hour or 24 hours before
the close. That uses only what was known before settlement, never the settled price (selecting on the outcome is
the leak kalshi_btc_fill.py exists to fix). The analysis then applies layer 16's own filter, 1% at each trade.

Seal: this only downloads. Comparing these trades with option fair values waits for the dates in
research/PREREGISTRATION_LAYER16_DRAFT.md. Standard library only. Run from collect/.
"""
import argparse, gzip, json, os, time, urllib.error, urllib.parse
from datetime import datetime, timedelta, timezone
from common import ROOT, get_json

BASE = "https://api.elections.kalshi.com/trade-api/v2"
COINBASE = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
OUT = os.path.join(ROOT, "data", "history", "kalshi", "trades", "KXBTCD")
CB = os.path.join(ROOT, "data", "history", "crypto", "coinbase_1m_days")
KRAKEN = os.path.join(ROOT, "data", "history", "crypto", "kraken_1s")
BAND = 0.02
PAUSE = 0.2


def utc(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")[:19] + "+00:00")


def paged(url, params, key, max_pages=200):
    cursor = None
    for _ in range(max_pages):
        q = dict(params, **({"cursor": cursor} if cursor else {}))
        for attempt in range(4):
            try:
                page = get_json(f"{url}?{urllib.parse.urlencode(q)}", retries=2, timeout=30)
                break
            except urllib.error.HTTPError as e:
                if e.code != 429 or attempt == 3:
                    raise
                time.sleep(5 * (attempt + 1))         # rate limited: wait and retry the same page
        yield from page.get(key, [])
        cursor = page.get("cursor")
        time.sleep(PAUSE)
        if not cursor:
            return


def coinbase_day(day):
    """1-minute candles for one UTC day, cached; today's is never cached because it is still filling."""
    path = os.path.join(CB, f"{day}.json")
    if os.path.exists(path):
        return json.load(open(path))
    start = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
    rows = []
    for k in range(5):                                 # 300 candles per request
        a, b = start + timedelta(minutes=300 * k), start + timedelta(minutes=min(300 * (k + 1), 1440) - 1)
        q = urllib.parse.urlencode({"granularity": 60, "start": a.isoformat(), "end": b.isoformat()})
        rows += get_json(f"{COINBASE}?{q}", retries=3, timeout=30)
        time.sleep(PAUSE)
    rows = sorted({r[0]: r for r in rows}.values())
    if start.date() < datetime.now(timezone.utc).date():
        os.makedirs(CB, exist_ok=True)
        json.dump(rows, open(path, "w"))
    return rows


def kraken_day(day):
    """Kraken XBT/USD: the last trade price in each second of one UTC day, from its full trade history (about
    170 requests a day). Only complete days are saved."""
    path = os.path.join(KRAKEN, f"{day}.json.gz")
    start = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
    if os.path.exists(path) or start.date() >= datetime.now(timezone.utc).date():
        return
    end = (start + timedelta(days=1)).timestamp()
    since, last = int(start.timestamp() * 1e9), {}
    while True:
        r = get_json(f"https://api.kraken.com/0/public/Trades?pair=XBTUSD&since={since}", retries=3, timeout=30)
        if r.get("error"):
            raise RuntimeError(f"kraken: {r['error']}")
        res = r["result"]
        trades = next(v for k, v in res.items() if k != "last")
        for tr in trades:
            t = float(tr[2])
            if t < end:
                last[int(t)] = float(tr[0])
        since = int(res["last"])
        if not trades or float(trades[-1][2]) >= end:
            break
        time.sleep(1.0)                                # Kraken's public limit is about one call a second
    os.makedirs(KRAKEN, exist_ok=True)
    with gzip.open(path + ".part", "wt") as f:
        json.dump(sorted(last.items()), f)
    os.replace(path + ".part", path)
    print(f"kraken {day}: {len(last)} seconds with a trade", flush=True)


class Prices:
    def __init__(self):
        self.close = {}

    def at(self, t):
        """Coinbase close of the minute ending at or before t (unix seconds)."""
        minute = int(t // 60) * 60 - 60
        for back in range(0, 600, 60):                 # tolerate a few missing minutes
            m = minute - back
            if m not in self.close:
                day = datetime.fromtimestamp(m, timezone.utc).strftime("%Y-%m-%d")
                for r in coinbase_day(day):
                    self.close[int(r[0])] = float(r[4])
            if m in self.close:
                return self.close[m]
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="YYYY-MM-DD (default: 8 days ago)")
    args = ap.parse_args()
    since = args.since or str((datetime.now(timezone.utc) - timedelta(days=8)).date())
    os.makedirs(OUT, exist_ok=True)
    min_close = int(datetime.fromisoformat(since).replace(tzinfo=timezone.utc).timestamp())
    markets = [m for m in paged(f"{BASE}/markets", {"series_ticker": "KXBTCD", "status": "settled", "limit": 1000,
                                                    "min_close_ts": min_close}, "markets")
               if m.get("strike_type") == "greater" and m.get("floor_strike") is not None]
    events = {}
    for m in markets:
        events.setdefault(m["event_ticker"], []).append(m)
    prices = Prices()
    done = skipped = 0
    for ev in sorted(events, key=lambda e: events[e][0]["close_time"]):
        path = os.path.join(OUT, f"{ev}.jsonl.gz")
        if os.path.exists(path):
            skipped += 1
            continue
        close = utc(events[ev][0]["close_time"]).timestamp()
        refs = [p for p in (prices.at(close - 3600), prices.at(close - 86400)) if p]
        keep = [m for m in events[ev]
                if refs and any(abs(float(m["floor_strike"]) / p - 1) <= BAND for p in refs)
                and float(m.get("volume_fp") or m.get("volume") or 0) > 0]
        rows, n = [], 0
        for m in keep:
            rows.append({"type": "market", "ticker": m["ticker"], "event": ev, "strike": float(m["floor_strike"]),
                         "open_time": m.get("open_time"), "close_time": m.get("close_time"), "result": m.get("result")})
            for tr in paged(f"{BASE}/markets/trades", {"ticker": m["ticker"], "limit": 1000}, "trades"):
                rows.append({"type": "trade", "t": tr.get("created_time"), "ticker": m["ticker"],
                             "trade_id": tr.get("trade_id"), "yes_price": float(tr["yes_price_dollars"]),
                             "count": float(tr.get("count_fp") or 0),
                             "taker_side": tr.get("taker_outcome_side") or tr.get("taker_side")})
                n += 1
        tmp = path + ".part"                           # written whole, then renamed: an interrupted run leaves no half file
        with gzip.open(tmp, "wt") as f:
            for r in rows:
                f.write(json.dumps(r, separators=(",", ":")) + "\n")
        os.replace(tmp, path)
        done += 1
        print(f"{ev}: {len(keep)} markets, {n} trades", flush=True)
    first = datetime.fromisoformat(since).date() - timedelta(days=1)
    day = first
    while day < datetime.now(timezone.utc).date():
        kraken_day(str(day))
        day += timedelta(days=1)
    print(f"since {since}: {done} events saved, {skipped} already there, {len(events)} settled events listed")


if __name__ == "__main__":
    main()
