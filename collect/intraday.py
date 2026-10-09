"""Save the last week of one-minute prices for SPY, the S&P 500 index (^GSPC), QQQ and the Nasdaq-100 (^NDX), for layer 7 (price discovery).

Free one-minute data only goes back about seven days, so this runs once a day from run_snapshot.sh and each
file overlaps the previous one; readers de-duplicate on timestamp. Run by hand from collect/: python3 intraday.py
"""
import os, sys
from datetime import datetime, timezone
from common import ROOT

OUT = os.path.join(ROOT, "data", "raw", "intraday")


def main():
    import yfinance as yf
    os.makedirs(OUT, exist_ok=True)
    df = yf.download(["SPY", "^GSPC", "QQQ", "^NDX"], period="7d", interval="1m", progress=False, auto_adjust=False)
    if df.empty:
        raise RuntimeError("no intraday data returned")
    path = os.path.join(OUT, f"intraday_{datetime.now(timezone.utc):%Y-%m-%d}.csv.gz")
    df.to_csv(path)
    print(f"{datetime.now(timezone.utc).isoformat()} intraday rows={len(df)} {df.index.min()} to {df.index.max()} -> {path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"intraday FAILED: {e!r}", file=sys.stderr)
        sys.exit(1)
