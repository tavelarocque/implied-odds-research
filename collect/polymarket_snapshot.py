"""Snapshot Polymarket's live order books for the daily S&P 500 and Nasdaq-100 markets.

Polymarket's price history has one price per moment and no bid/ask, so layer 6 had to assume a spread. These
snapshots record the real books (best 10 levels per side, for both outcomes) at the same moment as the options
and Kalshi snapshots. Daily markets are listed about a day ahead, so it checks today and the next few days.
"""
import json, sys, urllib.parse
from datetime import timedelta
from common import get_json, now_utc, out_path, write_jsonl_gz

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
KINDS = {"close": "spx-up-or-down-on-{d}", "open": "spx-opens-up-or-down-on-{d}", "ndx_close": "ndx-up-or-down-on-{d}"}
LEVELS = 10


def slug_date(d):
    return f"{d.strftime('%B').lower()}-{d.day}-{d.year}"


def best(levels, side):
    if not levels:
        return None
    prices = [float(x["price"]) for x in levels]
    return max(prices) if side == "bid" else min(prices)


def top(levels, side):
    srt = sorted(levels, key=lambda x: float(x["price"]), reverse=(side == "bid"))
    return [[float(x["price"]), float(x["size"])] for x in srt[:LEVELS]]


def main():
    ts = now_utc()
    rows = [{"type": "header", "collected_utc": ts.isoformat()}]
    found = 0
    for offset in range(0, 4):
        d = (ts - timedelta(hours=7) + timedelta(days=offset)).date()      # US calendar day, roughly
        if d.weekday() >= 5:
            continue
        for kind, pat in KINDS.items():
            slug = pat.format(d=slug_date(d))
            try:
                evs = get_json(f"{GAMMA}/events?{urllib.parse.urlencode({'slug': slug})}", retries=2)
            except Exception as e:
                print(f"  {slug}: {e!r}", file=sys.stderr)
                continue
            if not evs:
                continue
            m = evs[0]["markets"][0]
            if m.get("closed"):
                continue
            outcomes = json.loads(m["outcomes"]) if m.get("outcomes") else ["Up", "Down"]
            tokens = json.loads(m["clobTokenIds"])
            row = {"type": "market", "slug": slug, "kind": kind, "date": d.isoformat(), "end": m.get("endDate"),
                   "volume": m.get("volumeNum"), "liquidity": m.get("liquidityNum"), "books": {}}
            for name, tok in zip(outcomes, tokens):
                try:
                    b = get_json(f"{CLOB}/book?token_id={tok}", retries=2)
                except Exception as e:
                    print(f"  {slug} {name}: {e!r}", file=sys.stderr)
                    continue
                bids, asks = b.get("bids", []), b.get("asks", [])
                row["books"][name] = {"best_bid": best(bids, "bid"), "best_ask": best(asks, "ask"),
                                      "bids": top(bids, "bid"), "asks": top(asks, "ask"),
                                      "book_ts": b.get("timestamp"), "tick": b.get("tick_size")}
            rows.append(row)
            found += 1
    path = write_jsonl_gz(out_path("polymarket", ts), rows)
    summary = {r["slug"]: {k: (v["best_bid"], v["best_ask"]) for k, v in r["books"].items()} for r in rows[1:]}
    print(f"{ts.isoformat()} polymarket {found} open markets {summary} -> {path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"polymarket_snapshot FAILED: {e!r}", file=sys.stderr)
        sys.exit(1)
