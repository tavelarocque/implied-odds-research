"""Snapshot open Kalshi S&P 500 and Nasdaq-100 markets: prices, spreads, volume and strike ranges.

Kalshi's API also serves historical candlesticks for settled markets, so these live snapshots mainly
give us quotes taken at the same moment as the options snapshot, which history alone can't.
"""
import os, sys, urllib.parse
from common import get_json, now_utc, out_path, write_jsonl_gz

BASE = "https://api.elections.kalshi.com/trade-api/v2"
# The daily range ladders are what get matched against options; the hourly above/below series (KXINXU,
# KXNASDAQ100U, about 3,200 open contracts) are left out to keep a year of cloud snapshots small.
# Override with KALSHI_SERIES="KXINX,KXINXU,..." to collect others.
SERIES = [s.strip() for s in os.environ.get("KALSHI_SERIES", "KXINX,KXINXW,KXNASDAQ100").split(",") if s.strip()]
# Folder under data/raw. The crypto workflow saves to kalshi_crypto so stock analyses, which read every file in
# data/raw/kalshi, never see its runs (layer 5's snapshot spacing rule counts files).
KIND = os.environ.get("KALSHI_KIND", "kalshi")
DROP = {"rules_primary", "rules_secondary", "subtitle", "yes_sub_title", "no_sub_title",
        "early_close_condition", "custom_strike", "mve_selected_legs", "price_ranges"}


def open_markets(series):
    out, cursor = [], None
    while True:
        q = {"series_ticker": series, "status": "open", "limit": 1000}
        if cursor:
            q["cursor"] = cursor
        page = get_json(f"{BASE}/markets?{urllib.parse.urlencode(q)}")
        out += page.get("markets", [])
        cursor = page.get("cursor")
        if not cursor:
            return out


def main():
    ts = now_utc()
    rows = [{"type": "header", "collected_utc": ts.isoformat(), "series": SERIES}]
    counts = {}
    for s in SERIES:
        try:
            ms = open_markets(s)
        except Exception as e:
            print(f"  {s}: failed {e!r}", file=sys.stderr)
            continue
        counts[s] = len(ms)
        for m in ms:
            r = {k: v for k, v in m.items() if k not in DROP}
            r.update({"type": "market", "series": s})
            rows.append(r)
    path = write_jsonl_gz(out_path(KIND, ts), rows)
    print(f"{ts.isoformat()} {KIND} {counts} -> {path}")
    if KIND == "kalshi_crypto":
        try:  # logging only: a failure here must never fail the crypto run
            perp_funding(ts)
        except Exception as e:
            print(f"  kalshi perp funding: skipped ({e!r})", file=sys.stderr)


PERP_BASE = "https://external-api.kalshi.com/trade-api/v2/margin/funding_rates"
PERP = "KXBTCPERP"


def perp_funding(ts):
    """Log Kalshi's Bitcoin perpetual funding (live estimate + settled rates of the last 24 h) to data/raw/kalshi_perp.

    Added 2026-10-13, data only: no layer reads it and no pre-registered rule uses it (layer 11 keeps Binance/OKX
    funding). Kept so a later, separately pre-registered study (e.g. hedging layer 5 with the perp) has history."""
    est = get_json(f"{PERP_BASE}/estimate?ticker={PERP}", retries=2, timeout=20)
    q = urllib.parse.urlencode({"ticker": PERP, "start_ts": int(ts.timestamp()) - 86400, "end_ts": int(ts.timestamp())})
    hist = get_json(f"{PERP_BASE}/historical?{q}", retries=2, timeout=20).get("funding_rates", [])
    rows = [{"type": "header", "collected_utc": ts.isoformat(), "ticker": PERP},
            dict(est, type="estimate"), *[dict(h, type="settled") for h in hist]]
    path = write_jsonl_gz(out_path("kalshi_perp", ts), rows)
    print(f"  kalshi perp funding: estimate {est.get('funding_rate')} mark {est.get('mark_price')}; "
          f"{len(hist)} settled in 24 h -> {path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"kalshi_snapshot FAILED: {e!r}", file=sys.stderr)
        sys.exit(1)
