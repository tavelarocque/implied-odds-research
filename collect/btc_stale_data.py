"""Data for the stale-quote exploration: do Kalshi's hourly Bitcoin contracts lag the spot price?

Two parts, run separately so the Coinbase part can run while other Kalshi downloads are busy:
  python3 btc_stale_data.py sample     pick 400 hourly KXBTCD sets settling before FINAL_TEST_START (seed 13) and fetch
                                       their markets (archive, then live) -> data/history/kalshi/markets_KXBTCD_sample.jsonl.gz
  python3 btc_stale_data.py coinbase   Coinbase BTC-USD 1-minute candles for each set's last 7 hours
                                       -> data/history/crypto/coinbase_1m/<event>.json
  python3 btc_stale_data.py kalshi     Kalshi 1-minute candles, last 60 minutes, strikes within 1.5% of the settled price
                                       -> data/history/kalshi/candles_1m/KXBTCD/<ticker>.json.gz
Resumable. Run from collect/.
"""
import gzip, json, os, random, sys, time, urllib.parse
from datetime import datetime, timezone
from common import ROOT, get_json
from kalshi_history import BASE, HIST, DROP, ts, PAUSE
sys.path.insert(0, os.path.join(ROOT, "research"))
from config import FINAL_TEST_START

SAMPLE = os.path.join(HIST, "markets_KXBTCD_sample.jsonl.gz")
CB = os.path.join(ROOT, "data", "history", "crypto", "coinbase_1m")


def sample():
    events, cursor = [], None
    while True:
        q = {"series_ticker": "KXBTCD", "status": "settled", "limit": 200}
        if cursor:
            q["cursor"] = cursor
        page = get_json(f"{BASE}/events?{urllib.parse.urlencode(q)}")
        events += [e["event_ticker"] for e in page.get("events", [])]
        cursor = page.get("cursor")
        time.sleep(PAUSE)
        if not cursor:
            break
    rows, picked = [], []
    random.Random(13).shuffle(events)
    for ev in events:
        if len(picked) >= 400:
            break
        ms = []
        for url in (f"{BASE}/historical/markets?event_ticker={ev}&limit=300", f"{BASE}/markets?event_ticker={ev}&limit=300"):
            try:
                ms = get_json(url, retries=2).get("markets", [])
            except Exception:
                ms = []
            if ms:
                break
        time.sleep(PAUSE)
        if not ms or ms[0]["close_time"][:10] >= FINAL_TEST_START:
            continue
        close, opened = ts(ms[0]["close_time"]), ts(ms[0].get("open_time") or ms[0]["close_time"])
        if close - opened > 2 * 3600:                       # hourly sets only (the 5pm set opens a day ahead)
            continue
        picked.append(ev)
        rows += [{k: v for k, v in m.items() if k not in DROP} for m in ms]
    with gzip.open(SAMPLE, "wt") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    print(f"{len(picked)} hourly sets, {len(rows)} markets -> {SAMPLE} (from {len(events)} settled events)")


def load_sample():
    return [json.loads(l) for l in gzip.open(SAMPLE, "rt")]


def coinbase():
    os.makedirs(CB, exist_ok=True)
    ms = load_sample()
    closes = {m["event_ticker"]: ts(m["close_time"]) for m in ms}
    for i, (ev, end) in enumerate(sorted(closes.items())):
        p = os.path.join(CB, f"{ev}.json")
        if os.path.exists(p):
            continue
        out = []
        for s in range(end - 7 * 3600, end, 300 * 60):        # 300 candles per request
            e = min(s + 300 * 60, end)
            q = urllib.parse.urlencode({"granularity": 60, "start": datetime.fromtimestamp(s, timezone.utc).isoformat(),
                                        "end": datetime.fromtimestamp(e, timezone.utc).isoformat()})
            out += get_json(f"https://api.exchange.coinbase.com/products/BTC-USD/candles?{q}")
            time.sleep(0.15)
        out = sorted({c[0]: c for c in out}.values())          # [time, low, high, open, close, volume], time = minute start
        json.dump(out, open(p, "w"))
        if i % 50 == 0:
            print(f"  coinbase: {i} sets", flush=True)
    print("coinbase done")


def kalshi():
    out = os.path.join(HIST, "candles_1m", "KXBTCD")
    os.makedirs(out, exist_ok=True)
    n = 0
    for m in load_sample():
        v, k = m.get("expiration_value"), m.get("floor_strike")
        try:
            if v in (None, "") or k is None or abs(float(k) - float(v)) > 0.015 * float(v):
                continue
        except ValueError:
            continue
        p = os.path.join(out, f"{m['ticker']}.json.gz")
        if os.path.exists(p):
            continue
        end = ts(m["close_time"])
        q = urllib.parse.urlencode({"start_ts": end - 3600, "end_ts": end, "period_interval": 1})
        cs = None
        for url in (f"{BASE}/historical/markets/{m['ticker']}/candlesticks?{q}", f"{BASE}/series/KXBTCD/markets/{m['ticker']}/candlesticks?{q}"):
            try:
                cs = get_json(url, retries=2).get("candlesticks", [])
                break
            except Exception:
                continue
        time.sleep(PAUSE)
        if cs is None:
            continue
        with gzip.open(p, "wt") as f:
            json.dump({"ticker": m["ticker"], "period": 1, "candlesticks": cs}, f, separators=(",", ":"))
        n += 1
        if n % 500 == 0:
            print(f"  kalshi: {n} fetched", flush=True)
    print(f"kalshi done: {n} fetched")


if __name__ == "__main__":
    {"sample": sample, "coinbase": coinbase, "kalshi": kalshi}[sys.argv[1]]()
