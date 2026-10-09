"""Snapshot Deribit's Bitcoin options: bid, ask and mark (in BTC), mark implied volatility, each expiry's forward.

One public API call returns every BTC option's book summary. Only expiries within DERIBIT_MAX_DAYS (default 8) are
kept: research/PREREGISTRATION_BTC.md uses the first expiry after each Kalshi settlement, which is at most a day out.
Saved to data/raw/deribit_btc/<day>/deribit_btc_<HHMMSS>Z.jsonl.gz. Standard library only.
"""
import os, sys
from datetime import datetime, timezone
from common import get_json, now_utc, out_path, write_jsonl_gz

BASE = "https://www.deribit.com/api/v2/public"
MAX_DAYS = float(os.environ.get("DERIBIT_MAX_DAYS", "8"))
MONTHS = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}


def expiry_of(code):                          # 10OCT26 -> 2026-10-10 08:00 UTC (every Deribit expiry is 08:00 UTC)
    return datetime(2000 + int(code[-2:]), MONTHS[code[-5:-2]], int(code[:-5]), 8, tzinfo=timezone.utc)


def main():
    ts = now_utc()
    index = get_json(f"{BASE}/get_index_price?index_name=btc_usd")["result"]["index_price"]
    book = get_json(f"{BASE}/get_book_summary_by_currency?currency=BTC&kind=option")["result"]
    rows = [{"type": "header", "collected_utc": ts.isoformat(), "index_price": index, "source": "deribit"}]
    for o in book:
        _, code, strike, cp = o["instrument_name"].split("-")
        exp = expiry_of(code)
        days = (exp - ts).total_seconds() / 86400
        if not 0 < days <= MAX_DAYS:
            continue
        rows.append({"type": "option", "instrument": o["instrument_name"], "expiry": exp.isoformat(),
                     "strike": float(strike), "cp": cp, "bid": o.get("bid_price"), "ask": o.get("ask_price"),
                     "mark": o.get("mark_price"), "mark_iv": o.get("mark_iv"),
                     "underlying_price": o.get("underlying_price"), "open_interest": o.get("open_interest"),
                     "volume": o.get("volume")})
    path = write_jsonl_gz(out_path("deribit_btc", ts), rows)
    print(f"{ts.isoformat()} deribit btc: index {index:,.0f}, {len(rows) - 1} options -> {path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"deribit_snapshot FAILED: {e!r}", file=sys.stderr)
        sys.exit(1)
