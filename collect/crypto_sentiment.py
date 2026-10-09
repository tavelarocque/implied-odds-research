"""Crypto crowd-mood history, for the Bitcoin sentiment exploration.

- Crypto Fear & Greed Index (alternative.me): daily 0-100, from 2018. Built from volatility, momentum, social media,
  surveys, dominance and search trends. Each value is stamped 00:00 UTC of the day it describes going into.
- Binance BTCUSDT perpetual funding rate: every 8 hours, from 2022-01-01. Positive = longs pay shorts, i.e. the
  leveraged crowd leans long.
Writes data/history/attention/fear_greed_daily.csv and binance_funding_btc.csv. Standard library only.

Run from collect/:  python3 crypto_sentiment.py
"""
import csv, os, time
from datetime import datetime, timezone
from common import ROOT, get_json

OUT = os.path.join(ROOT, "data", "history", "attention")


def main():
    os.makedirs(OUT, exist_ok=True)
    d = get_json("https://api.alternative.me/fng/?limit=0&format=json")["data"]
    rows = sorted((datetime.fromtimestamp(int(x["timestamp"]), timezone.utc).strftime("%Y-%m-%d"), int(x["value"]),
                   x["value_classification"]) for x in d)
    with open(os.path.join(OUT, "fear_greed_daily.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "value", "label"]); w.writerows(rows)
    print(f"fear & greed: {len(rows)} days, {rows[0][0]} to {rows[-1][0]}")

    start = int(datetime(2022, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    now = int(time.time() * 1000)
    fr = []
    while start < now:
        page = get_json(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&startTime={start}&limit=1000")
        if not page:
            break
        fr += [(datetime.fromtimestamp(p["fundingTime"] / 1000, timezone.utc).isoformat(), float(p["fundingRate"])) for p in page]
        start = page[-1]["fundingTime"] + 1
        time.sleep(0.3)
    with open(os.path.join(OUT, "binance_funding_btc.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["time_utc", "funding_rate"]); w.writerows(fr)
    print(f"binance funding: {len(fr)} rates, {fr[0][0][:10]} to {fr[-1][0][:10]}")


if __name__ == "__main__":
    main()
