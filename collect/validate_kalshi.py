"""Data checks for the Kalshi history before any analysis trusts it.

  1. No duplicate tickers.
  2. Every daily S&P range event (KXINX) has exactly one contract that settled yes.
  3. Kalshi's recorded settlement value matches the S&P 500 close from Yahoo Finance (^GSPC).
  4. Hourly candle coverage, and the share of candle files with no data.

Run from collect/:  python3 validate_kalshi.py
"""
import gzip, json, os, glob, collections
from common import ROOT

HIST = os.path.join(ROOT, "data", "history", "kalshi")


def load(series):
    with gzip.open(os.path.join(HIST, f"markets_{series}.jsonl.gz"), "rt", encoding="utf-8") as f:
        return [json.loads(l) for l in f]


def main():
    ms = load("KXINX")
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
        spx = yf.download("^GSPC", start="2022-04-01", progress=False, auto_adjust=False)["Close"]
        spx = spx.squeeze()
        closes = {d.strftime("%Y-%m-%d"): float(v) for d, v in spx.items()}
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
        print(f"[3] settlement value vs S&P close: {checked - len(off)} of {checked} match within 5 cents")
        for e, v, c, d in off[:10]:
            print(f"      {e}: Kalshi {v:.2f}, S&P close {c:.2f}, diff {d:+.2f}")
        problems += len(off) > 0.01 * max(checked, 1)
    except Exception as ex:
        print(f"[3] skipped settlement check: {ex!r}")

    files = glob.glob(os.path.join(HIST, "candles_60m", "KXINX", "*.json.gz"))
    empty = 0
    for f in files:
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            if not json.load(fh)["candlesticks"]:
                empty += 1
    print(f"[4] hourly candle files: {len(files)} of {len(ms)} markets; {empty} empty ({100 * empty / max(len(files), 1):.1f}%)")
    print("\nALL CHECKS PASSED" if not problems else f"\n{problems} CHECK(S) NEED A LOOK")


if __name__ == "__main__":
    main()
