"""Kalshi's 5pm ET Bitcoin sets (KXBTCD events ending in 17) and their hourly candles, without pulling every hourly set.

The full KXBTCD history has a set every hour, which is far more than the sentiment exploration needs. This lists the
series' settled events, keeps the 5pm ones, fetches each one's markets (archive first, then live), and the hourly
candles of the last 7 hours before settlement for strikes within 4% of the settled price, on sets settling before
FINAL_TEST_START (the development sample; the holdout is not touched).
Writes data/history/kalshi/markets_KXBTCD_5pm.jsonl.gz and candles_60m/KXBTCD/<ticker>.json.gz. Resumable.

Run from collect/:  python3 kalshi_btc_daily.py
"""
import gzip, json, os, time, urllib.parse
from common import ROOT, get_json
import sys
from kalshi_history import BASE, HIST, DROP, ts, PAUSE
sys.path.insert(0, os.path.join(ROOT, "research"))
from config import FINAL_TEST_START
# LAYER11_HOLDOUT=1 fetches the holdout's candles instead (research/PREREGISTRATION_LAYER11.md, test A), and only those.
HOLDOUT_WINDOW = (FINAL_TEST_START, "2026-09-30") if os.environ.get("LAYER11_HOLDOUT") == "1" else None


def main():
    events, cursor = [], None
    while True:
        q = {"series_ticker": "KXBTCD", "status": "settled", "limit": 200}
        if cursor:
            q["cursor"] = cursor
        page = get_json(f"{BASE}/events?{urllib.parse.urlencode(q)}")
        events += [e["event_ticker"] for e in page.get("events", []) if e["event_ticker"].endswith("17")]
        cursor = page.get("cursor")
        time.sleep(PAUSE)
        if not cursor:
            break
    print(f"{len(events)} settled 5pm sets")
    path = os.path.join(HIST, "markets_KXBTCD_5pm.jsonl.gz")
    have = {}
    if os.path.exists(path):
        have = {json.loads(l)["ticker"]: json.loads(l) for l in gzip.open(path, "rt")}
    done_events = {m["event_ticker"] for m in have.values()}
    for i, ev in enumerate(sorted(set(events) - done_events)):
        ms = []
        for url in (f"{BASE}/historical/markets?event_ticker={ev}&limit=200", f"{BASE}/markets?event_ticker={ev}&limit=200"):
            try:
                ms = get_json(url, retries=2).get("markets", [])
            except Exception:
                ms = []
            if ms:
                break
        for m in ms:
            have[m["ticker"]] = {k: v for k, v in m.items() if k not in DROP}
        time.sleep(PAUSE)
        if i % 100 == 0:
            print(f"  markets: {i} sets fetched", flush=True)
    with gzip.open(path, "wt") as f:
        for m in sorted(have.values(), key=lambda m: m.get("close_time") or ""):
            f.write(json.dumps(m, separators=(",", ":")) + "\n")
    print(f"{len(have)} markets -> {path}")

    out = os.path.join(HIST, "candles_60m", "KXBTCD")
    os.makedirs(out, exist_ok=True)
    fetched = 0
    for m in have.values():
        v, k = m.get("expiration_value"), m.get("floor_strike")
        try:
            day = (m.get("close_time") or "")[:10]
            if HOLDOUT_WINDOW:
                if not (HOLDOUT_WINDOW[0] <= day <= HOLDOUT_WINDOW[1]):
                    continue
            elif day >= FINAL_TEST_START:
                continue
            if v in (None, "") or k is None or abs(float(k) - float(v)) > 0.04 * float(v):
                continue
        except ValueError:
            continue
        p = os.path.join(out, f"{m['ticker']}.json.gz")
        if os.path.exists(p):
            continue
        end = ts(m["close_time"])
        q = urllib.parse.urlencode({"start_ts": end - 7 * 3600, "end_ts": end, "period_interval": 60})
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
            json.dump({"ticker": m["ticker"], "period": 60, "candlesticks": cs}, f, separators=(",", ":"))
        fetched += 1
        if fetched % 500 == 0:
            print(f"  candles: {fetched} fetched", flush=True)
    print(f"candles: {fetched} fetched")


if __name__ == "__main__":
    main()
