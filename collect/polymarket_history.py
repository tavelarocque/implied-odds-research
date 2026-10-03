"""Pull Polymarket's daily S&P 500 markets and their price history.

Polymarket's daily S&P markets have predictable slugs:
    spx-up-or-down-on-january-21-2026          (close vs previous close)
    spx-opens-up-or-down-on-january-29-2026    (open vs previous close)
so we look each trading day up directly instead of relying on search or tags.

Usage (run from the collect/ folder):
    python3 polymarket_history.py events --start 2025-01-01      # find markets, save metadata + rules + result
    python3 polymarket_history.py prices --fidelity 10           # 10-minute price history for each found market

Resumable: rerunning skips what's on disk. The rules text is kept on purpose, so settlement terms can be
compared with Kalshi's before treating any price gap as an arbitrage.
"""
import argparse, gzip, json, os, re, sys, time, urllib.parse
from datetime import date, datetime, timedelta, timezone
from common import ROOT, get_json

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
OUT = os.path.join(ROOT, "data", "history", "polymarket")
KINDS = {"close": "spx-up-or-down-on-{d}", "open": "spx-opens-up-or-down-on-{d}",
         "ndx_close": "ndx-up-or-down-on-{d}"}
PAUSE = 0.15


def slug_date(d):
    return f"{d.strftime('%B').lower()}-{d.day}-{d.year}"


def weekdays(start, end):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def find_events(start, end):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "events.jsonl.gz")
    have = {}
    if os.path.exists(path):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for l in f:
                r = json.loads(l)
                have[r["slug"]] = r
    checked = found = 0
    for d in weekdays(start, end):
        for kind, pat in KINDS.items():
            slug = pat.format(d=slug_date(d))
            if slug in have:
                continue
            checked += 1
            try:
                evs = get_json(f"{GAMMA}/events?{urllib.parse.urlencode({'slug': slug})}")
            except Exception as e:
                print(f"  {slug}: {e!r}", file=sys.stderr)
                continue
            time.sleep(PAUSE)
            if not evs:
                continue
            e = evs[0]
            for m in e.get("markets", []):
                have[slug] = {
                    "slug": slug, "kind": kind, "date": d.isoformat(), "event_id": e.get("id"),
                    "title": e.get("title"), "question": m.get("question"), "condition_id": m.get("conditionId"),
                    "outcomes": m.get("outcomes"), "outcome_prices": m.get("outcomePrices"),
                    "clob_token_ids": m.get("clobTokenIds"), "closed": m.get("closed"),
                    "start": m.get("startDate"), "end": m.get("endDate"), "volume": m.get("volumeNum"),
                    "liquidity": m.get("liquidityNum"), "rules": m.get("description"),
                    "resolution_source": m.get("resolutionSource"),
                }
                found += 1
                break
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for r in sorted(have.values(), key=lambda r: (r["date"], r["kind"])):
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    dates = sorted(r["date"] for r in have.values())
    print(f"checked {checked} new slugs, found {found} new markets; {len(have)} total"
          + (f", {dates[0]} to {dates[-1]}" if dates else ""))


def pull_prices(fidelity):
    path = os.path.join(OUT, "events.jsonl.gz")
    with gzip.open(path, "rt", encoding="utf-8") as f:
        evs = [json.loads(l) for l in f]
    outdir = os.path.join(OUT, f"prices_{fidelity}m")
    os.makedirs(outdir, exist_ok=True)
    fetched = skipped = failed = 0
    for e in evs:
        dest = os.path.join(outdir, f"{e['slug']}.json.gz")
        if os.path.exists(dest) or not e.get("clob_token_ids"):
            skipped += 1
            continue
        tokens = json.loads(e["clob_token_ids"])
        outcomes = json.loads(e["outcomes"]) if e.get("outcomes") else [str(i) for i in range(len(tokens))]
        # Resolved markets return an empty history for interval=max; an explicit start/end window works.
        def ts(iso):
            # Polymarket timestamps vary in fractional-second digits, which Python 3.9 can't parse; drop them.
            iso = re.sub(r"\.\d+", "", iso.replace("Z", "+00:00"))
            return int(datetime.fromisoformat(iso).timestamp())
        end = ts(e["end"]) + 3600
        start = ts(e["start"]) - 3600 if e.get("start") else end - 3 * 86400
        series = {}
        try:
            for name, tok in zip(outcomes, tokens):
                q = {"market": tok, "startTs": start, "endTs": end, "fidelity": fidelity}
                series[name] = get_json(f"{CLOB}/prices-history?{urllib.parse.urlencode(q)}").get("history", [])
                time.sleep(PAUSE)
        except Exception as ex:
            print(f"  {e['slug']}: {ex!r}", file=sys.stderr)
            failed += 1
            continue
        if not any(series.values()):
            failed += 1          # don't save an empty file: a later run should retry this market
            continue
        with gzip.open(dest, "wt", encoding="utf-8") as f:
            json.dump({"slug": e["slug"], "fidelity": fidelity, "history": series}, f, separators=(",", ":"))
        fetched += 1
    print(f"prices {fidelity}m: {fetched} fetched, {skipped} skipped, {failed} failed")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["events", "prices"])
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--end", default=date.today().isoformat())
    ap.add_argument("--fidelity", type=int, default=10, help="minutes per price point")
    a = ap.parse_args()
    if a.what == "events":
        find_events(date.fromisoformat(a.start), date.fromisoformat(a.end))
    else:
        pull_prices(a.fidelity)
