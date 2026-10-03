"""Snapshot the SPX option chain from Cboe's delayed-quote feed (about 15 minutes delayed).

Keeps only short-dated expiries, which are the ones that line up with Kalshi's daily and weekly
S&P 500 contracts and are what Breeden-Litzenberger needs. Each row is one option quote; the first
row is a header record with the underlying price and the feed timestamp.
"""
import re, sys
from datetime import date, datetime
from common import get_json, now_utc, out_path, write_jsonl_gz

URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/_SPX.json"
MAX_DAYS = 14          # keep expiries up to two weeks out
OCC = re.compile(r"^(SPXW?)(\d{6})([CP])(\d{8})$")
FIELDS = ["bid", "ask", "bid_size", "ask_size", "iv", "open_interest", "volume", "delta", "gamma",
          "vega", "theta", "theo", "last_trade_price", "last_trade_time", "prev_day_close"]


def main():
    ts = now_utc()
    raw = get_json(URL)
    d = raw["data"]
    today = ts.date()
    rows = [{"type": "header", "collected_utc": ts.isoformat(), "feed_timestamp": raw.get("timestamp"),
             "underlying": "SPX", "spot": d.get("current_price"), "spot_bid": d.get("bid"),
             "spot_ask": d.get("ask"), "prev_close": d.get("prev_day_close")}]
    kept = 0
    for o in d["options"]:
        m = OCC.match(o["option"])
        if not m:
            continue
        root, ymd, cp, strike = m.groups()
        exp = date(2000 + int(ymd[:2]), int(ymd[2:4]), int(ymd[4:]))
        dte = (exp - today).days
        if dte < 0 or dte > MAX_DAYS:
            continue
        row = {"type": "option", "symbol": o["option"], "root": root, "expiry": exp.isoformat(),
               "dte": dte, "cp": cp, "strike": int(strike) / 1000}
        row.update({k: o.get(k) for k in FIELDS})
        rows.append(row)
        kept += 1
    path = write_jsonl_gz(out_path("spx_options", ts), rows)
    print(f"{ts.isoformat()} spx_options spot={d.get('current_price')} kept={kept} -> {path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"options_snapshot FAILED: {e!r}", file=sys.stderr)
        sys.exit(1)
