"""LEAKAGE CHECK (Kapoor & Narayanan, type L2/L3.3): does picking strikes "within 4% of the settled price" drop
layer 11's losing trades?

collect/kalshi_btc_daily.py fetched candles only for strikes with |K - settle| <= 4% of settle. A downside long shot
(YES mid >= 90c, so K below spot) LOSES for the seller when Bitcoin settles below K. If Bitcoin fell far enough in the
last hours, settle < K / 1.04 and the contract was never downloaded: the losing trade is silently missing.

Check, using only Bitcoin prices (Coinbase hourly) and Kalshi's market list (no holdout outcomes are analysed here;
the markets list for the holdout is used only to count strikes the filter dropped):
  for every 5pm set, the Coinbase price 1h and 3h before settlement (S_h);
  strikes K below S_h by up to 6% (where layer 11's long shots sit) that were EXCLUDED by the 4% rule;
  how many of those settled NO (Bitcoin finished below K): each is a layer 11 loss the sample cannot see.
Reports counts for the development sample. For the holdout it reports only how many strikes the filter dropped,
not their outcomes.
"""
import gzip, json, os, sys, time, urllib.parse
from datetime import datetime, timezone
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "collect"))
from common import get_json
OUT = os.path.join(ROOT, "data", "history", "crypto", "coinbase_1h.csv")


def coinbase_hourly(start, end):
    if os.path.exists(OUT):
        d = pd.read_csv(OUT)
        if len(d) and d.t.min() <= start and d.t.max() >= end - 7200:
            return d.set_index("t").close
    rows = []
    for s in range(start, end, 300 * 3600):
        e = min(s + 300 * 3600, end)
        q = urllib.parse.urlencode({"granularity": 3600, "start": datetime.fromtimestamp(s, timezone.utc).isoformat(),
                                    "end": datetime.fromtimestamp(e, timezone.utc).isoformat()})
        rows += get_json(f"https://api.exchange.coinbase.com/products/BTC-USD/candles?{q}")
        time.sleep(0.2)
    d = pd.DataFrame(sorted({r[0]: r for r in rows}.values()), columns=["t", "low", "high", "open", "close", "vol"])
    d.to_csv(OUT, index=False)
    return d.set_index("t").close


def main():
    ms = [json.loads(l) for l in gzip.open(os.path.join(ROOT, "data", "history", "kalshi", "markets_KXBTCD_5pm.jsonl.gz"), "rt")]
    ms = [m for m in ms if m["event_ticker"].endswith("17") and m.get("strike_type") == "greater"
          and m.get("expiration_value") not in (None, "") and m.get("result") in ("yes", "no")]
    df = pd.DataFrame({"event": [m["event_ticker"] for m in ms], "close": [m["close_time"] for m in ms],
                       "K": [float(m["floor_strike"]) for m in ms],
                       "settle": [float(str(m["expiration_value"]).replace(",", "")) for m in ms],
                       "y": [m["result"] for m in ms]})
    df["close_ts"] = pd.to_datetime(df.close, utc=True).map(lambda t: int(t.timestamp()))
    df["day"] = df.close.str[:10]
    px = coinbase_hourly(int(df.close_ts.min()) - 4 * 3600, int(df.close_ts.max()) + 3600)
    # hourly candle t = start of hour; the close of the candle that ENDS at close_ts - h hours
    for h in (1, 3):
        df[f"S{h}"] = (df.close_ts - h * 3600 - 3600).map(px)
    df["kept"] = (df.K - df.settle).abs() <= 0.04 * df.settle
    for sample, sel in (("development (before 2026-04-01)", df.day < "2026-04-01"),
                        ("holdout (2026-04-01 to 09-30)", (df.day >= "2026-04-01") & (df.day <= "2026-09-30"))):
        x = df[sel]
        print(f"\n{sample}: {x.event.nunique()} sets")
        for h in (1, 3):
            z = x[(x.K < x[f"S{h}"]) & (x.K > x[f"S{h}"] * 0.94)]         # strikes below spot by up to 6%
            dropped = z[~z.kept]
            line = (f"  {h}h before: strikes up to 6% below spot {len(z)}, dropped by the 4% filter {len(dropped)} "
                    f"on {dropped.event.nunique()} days")
            if sample.startswith("development"):
                lost = dropped[dropped.y == "no"]
                big = x.drop_duplicates("event")
                mv = (big.settle / big[f"S{h}"] - 1)
                line += (f"; of those, settled NO (a layer 11 loss if it had been a long shot): {len(lost)} on "
                         f"{lost.event.nunique()} days {sorted(lost.day.unique())[:8]}"
                         f"\n     Bitcoin's move over the last {h}h: worst {100 * mv.min():+.1f}%, days below -3%: "
                         f"{int((mv < -0.03).sum())}, below -4%: {int((mv < -0.04).sum())}")
            print(line)


if __name__ == "__main__":
    main()
