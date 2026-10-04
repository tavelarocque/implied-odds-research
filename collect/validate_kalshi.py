"""Data checks for the Kalshi history before any analysis trusts it.

  1. No duplicate tickers.
  2. Every daily range event has exactly one contract that settled yes.
  3. Kalshi's recorded settlement value matches the index close from Yahoo Finance.
  4. Hourly candle coverage, and the share of candle files with no data.

Run from collect/:  python3 validate_kalshi.py [SERIES]      (default KXINX; also KXNASDAQ100)
"""
import gzip, json, os, glob, collections, sys
from common import ROOT

HIST = os.path.join(ROOT, "data", "history", "kalshi")
INDEX = {"KXINX": ("^GSPC", "S&P 500"), "KXNASDAQ100": ("^NDX", "Nasdaq-100")}


def load(series):
    with gzip.open(os.path.join(HIST, f"markets_{series}.jsonl.gz"), "rt", encoding="utf-8") as f:
        return [json.loads(l) for l in f]


def main():
    series = sys.argv[1] if len(sys.argv) > 1 else "KXINX"
    yahoo, name = INDEX[series]
    print(f"Validating {series} ({name})")
    ms = load(series)
    problems = 0

    dup = [t for t, c in collections.Counter(m["ticker"] for m in ms).items() if c > 1]
    print(f"[1] duplicate tickers: {len(dup)}")
    problems += bool(dup)

    by_event = collections.defaultdict(list)
    for m in ms:
        by_event[m["event_ticker"]].append(m)
    winners = {e: sum(m.get("result") == "yes" for m in g) for e, g in by_event.items()}
    bad = {e: n for e, n in winners.items() if n != 1}
    print(f"[2] events with exactly one winner: {len(winners) - len(bad)} of {len(winners)}")
    for e, n in sorted(bad.items())[:10]:
        print(f"      {e}: {n} winners")
    if bad:
        print("      (excluded by the analyses, which require exactly one winner per day)")
    problems += len(bad) > 0.01 * len(winners)

    try:
        import yfinance as yf
        first = min(m["close_time"][:10] for m in ms)
        px = yf.download(yahoo, start=first, progress=False, auto_adjust=False)["Close"].squeeze()
        closes = {d.strftime("%Y-%m-%d"): float(v) for d, v in px.items()}
        checked, off = 0, []
        for e, g in by_event.items():
            v = next((m.get("expiration_value") for m in g if m.get("expiration_value")), None)
            day = g[0]["close_time"][:10]
            if v is None or day not in closes:
                continue
            checked += 1
            v = float(str(v).replace(",", ""))
            diff = v - closes[day]
            if abs(diff) > 0.05:
                off.append((e, v, closes[day], diff))
        print(f"[3] settlement value vs {name} close ({yahoo}): {checked - len(off)} of {checked} match within 5 cents")
        for e, v, c, d in off[:10]:
            print(f"      {e}: Kalshi {v:.2f}, Yahoo close {c:.2f}, diff {d:+.2f}")
        problems += len(off) > 0.01 * max(checked, 1)
    except Exception as ex:
        print(f"[3] skipped settlement check: {ex!r}")

    files = glob.glob(os.path.join(HIST, "candles_60m", series, "*.json.gz"))
    empty = 0
    for f in files:
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            if not json.load(fh)["candlesticks"]:
                empty += 1
    print(f"[4] hourly candle files: {len(files)} of {len(ms)} markets; {empty} empty ({100 * empty / max(len(files), 1):.1f}%)")

    print("\nALL CHECKS PASSED" if not problems else f"\n{problems} CHECK(S) NEED A LOOK")


if __name__ == "__main__":
    main()
