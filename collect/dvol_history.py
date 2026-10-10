"""Deribit's Bitcoin volatility index (DVOL, 30-day implied volatility from BTC options), hourly, from 2021-03-24.
Writes data/history/crypto/dvol_btc_1h.csv (t = start of the hour in ms, open/high/low/close). Standard library only.

Run from collect/:  python3 dvol_history.py
"""
import csv, os, time
from common import ROOT, get_json

OUT = os.path.join(ROOT, "data", "history", "crypto", "dvol_btc_1h.csv")
URL = "https://www.deribit.com/api/v2/public/get_volatility_index_data?currency=BTC&resolution=3600"


def main():
    start, end = 1616544000000, int(time.time() * 1000)          # 2021-03-24
    rows, step = {}, 900 * 3600 * 1000
    for s in range(start, end, step):
        e = min(s + step, end)
        for r in get_json(f"{URL}&start_timestamp={s}&end_timestamp={e}")["result"]["data"]:
            rows[r[0]] = r
        time.sleep(0.2)
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["t", "open", "high", "low", "close"]); w.writerows(sorted(rows.values()))
    print(f"DVOL: {len(rows)} hours -> {OUT}")


if __name__ == "__main__":
    main()
