"""Snapshot index option chains (SPX and NDX by default) from Cboe's delayed-quote feed (about 15 minutes delayed).

Keeps only short-dated expiries, which are the ones that line up with Kalshi's daily and weekly
S&P 500 contracts and are what Breeden-Litzenberger needs. Each row is one option quote; the first
row is a header record with the underlying price and the feed timestamp.
"""
import os, re, sys
from datetime import date, datetime
from common import get_json, now_utc, out_path, write_jsonl_gz

URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/_{u}.json"
# SPX (with PM-settled SPXW) for the S&P 500, NDX (with PM-settled NDXP) for the Nasdaq-100.
UNDERLYINGS = [u.strip() for u in os.environ.get("SNAP_UNDERLYINGS", "SPX,NDX").split(",") if u.strip()]
MAX_DAYS = int(os.environ.get("SNAP_MAX_DAYS", 14))          # keep expiries up to two weeks out
MAX_MONEYNESS = float(os.environ.get("SNAP_MAX_MONEYNESS", 0) or 0)  # e.g. 0.08 keeps strikes within 8% of spot; 0 keeps all
OCC = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")
FIELDS = ["bid", "ask", "bid_size", "ask_size", "iv", "open_interest", "volume", "delta", "gamma",
          "vega", "theta", "theo", "last_trade_price", "last_trade_time", "prev_day_close"]


def snapshot(u):
    ts = now_utc()
    raw = get_json(URL.format(u=u))
    d = raw["data"]
    today = ts.date()
    rows = [{"type": "header", "collected_utc": ts.isoformat(), "feed_timestamp": raw.get("timestamp"),
             "underlying": u, "spot": d.get("current_price"), "spot_bid": d.get("bid"),
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
        if MAX_MONEYNESS and d.get("current_price") and abs(int(strike) / 1000 / d["current_price"] - 1) > MAX_MONEYNESS:
            continue
        row = {"type": "option", "symbol": o["option"], "root": root, "expiry": exp.isoformat(),
               "dte": dte, "cp": cp, "strike": int(strike) / 1000}
        row.update({k: o.get(k) for k in FIELDS})
        rows.append(row)
        kept += 1
    path = write_jsonl_gz(out_path(f"{u.lower()}_options", ts), rows)
    print(f"{ts.isoformat()} {u.lower()}_options spot={d.get('current_price')} kept={kept} -> {path}")


def main():
    failed = []
    for u in UNDERLYINGS:
        try:
            snapshot(u)
        except Exception as e:                      # one index failing must not lose the others
            print(f"options_snapshot {u} FAILED: {e!r}", file=sys.stderr)
            failed.append(u)
    if failed and len(failed) == len(UNDERLYINGS):
        sys.exit(1)


if __name__ == "__main__":
    main()
