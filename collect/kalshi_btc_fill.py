"""Fill a selection gap in collect/kalshi_btc_daily.py (found 2026-10-09, before layer 11's holdout test was run).

kalshi_btc_daily.py fetched candles only for strikes within 4% of the SETTLED price. That uses the outcome to choose
the sample (Kapoor & Narayanan's leakage type L2/L3.3): if Bitcoin fell more than about 4% in the last hours, the
downside long shots that then paid out were never downloaded, so layer 11 could not see those losses. On the
development sample this hides at most 3 such contracts at 3 hours (2024-08-15, 2024-11-13, 2026-02-05) and none at 1h
(research/check_strike_selection.py).

This adds candles for every strike within 6% BELOW the Bitcoin price 1 or 3 hours before settlement (Coinbase hourly,
data/history/crypto/coinbase_1h.csv), i.e. chosen with information available at decision time. Same candle request
and storage as kalshi_btc_daily.py. Resumable.

Run from collect/:  LAYER11_HOLDOUT=1 python3 kalshi_btc_fill.py   (holdout window)   or without it (development)

Layer 12 (Kronos, research/PREREGISTRATION_LAYER12.md) scores every strike within 6% EITHER side of the decision-time
price, so it also needs the strikes above it:  FILL_ABOVE=1 FILL_FROM=2025-09-01 python3 kalshi_btc_fill.py
"""
import gzip, json, os, sys, time, urllib.parse
import pandas as pd
from common import ROOT, get_json
from kalshi_history import BASE, HIST, ts, PAUSE
sys.path.insert(0, os.path.join(ROOT, "research"))
from config import FINAL_TEST_START

WINDOW = (FINAL_TEST_START, "2026-09-30") if os.environ.get("LAYER11_HOLDOUT") == "1" else ("2000-01-01", FINAL_TEST_START)


def main():
    px = pd.read_csv(os.path.join(ROOT, "data", "history", "crypto", "coinbase_1h.csv")).set_index("t").close
    out = os.path.join(HIST, "candles_60m", "KXBTCD")
    todo = []
    for l in gzip.open(os.path.join(HIST, "markets_KXBTCD_5pm.jsonl.gz"), "rt"):
        m = json.loads(l)
        day = (m.get("close_time") or "")[:10]
        holdout = os.environ.get("LAYER11_HOLDOUT") == "1"
        if day < os.environ.get("FILL_FROM", ""):
            continue
        if (holdout and not (FINAL_TEST_START <= day <= "2026-09-30")) or (not holdout and day >= FINAL_TEST_START):
            continue
        if not m["event_ticker"].endswith("17") or m.get("strike_type") != "greater" or m.get("floor_strike") is None:
            continue
        if os.path.exists(os.path.join(out, f"{m['ticker']}.json.gz")):
            continue
        end = ts(m["close_time"]); K = float(m["floor_strike"])
        spots = [px.get(end - h * 3600 - 3600) for h in (1, 3)]
        above = os.environ.get("FILL_ABOVE") == "1"
        if any(s is not None and s == s and s * 0.94 < K < (s * 1.06 if above else s) for s in spots):
            todo.append(m)
    print(f"{WINDOW[0]} to {WINDOW[1]}: {len(todo)} strikes to add", flush=True)
    for i, m in enumerate(todo):
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
        with gzip.open(os.path.join(out, f"{m['ticker']}.json.gz"), "wt") as f:
            json.dump({"ticker": m["ticker"], "period": 60, "candlesticks": cs}, f, separators=(",", ":"))
        if i % 100 == 0:
            print(f"  fill: {i} of {len(todo)}", flush=True)
    print("fill done", flush=True)


if __name__ == "__main__":
    main()
