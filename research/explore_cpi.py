"""Layer 10, EXPLORATORY: Kalshi's CPI markets vs the Cleveland Fed's inflation nowcast.

Development sample only (releases before FINAL_TEST_START). Looks for a hypothesis, tests nothing.

At 10:30 ET on the day before each CPI release (the nowcast updates around 10:00 ET), compare for every Kalshi
"CPI above k%" contract (KXCPI headline month-over-month, KXCPICORE core):
  - Kalshi: the yes bid, ask and mid of the last hourly candle at or before that time
  - Nowcast: P(published value > k) = P(unrounded change >= k + 0.05), the unrounded change taken as normal around the
    Cleveland Fed's nowcast, with a standard deviation equal to the nowcast's day-before error over 2013-07 to 2021-06,
    before Kalshi listed CPI markets, so nothing is tuned on the comparison sample.
Settlement: Kalshi's own result. Intervals resample whole releases (2,000 draws).

Run from the project root, after:
    python3 collect/kalshi_history.py markets --series KXCPI KXCPICORE
    python3 collect/kalshi_history.py candles --period 60 --series KXCPI KXCPICORE --hours-before 72
and saving https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json to
data/history/macro/cleveland_nowcast_month.json.
"""
import gzip, json, math, os, sys
from datetime import datetime, timedelta, timezone
import numpy as np
import pandas as pd
from scipy.stats import norm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research"))
from config import FINAL_TEST_START
KH = os.path.join(ROOT, "data", "history", "kalshi")
NOW = os.path.join(ROOT, "data", "history", "macro", "cleveland_nowcast_month.json")
SERIES = {"KXCPI": ("CPI Inflation", "Actual CPI Inflation"), "KXCPICORE": ("Core CPI Inflation", "Actual Core CPI Inflation")}
MON = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}
SIGMA_END = "2021-06"
FEE = 0.07
rng = np.random.default_rng(10)


def nowcast_paths():
    """{(target 'YYYY-M', series name): pd.Series of nowcast by date} plus actual (unrounded) per target and name."""
    paths, actual = {}, {}
    for c in json.load(open(NOW)):
        tgt = c["chart"]["subcaption"]
        ty, tm = map(int, tgt.split("-"))
        labels = [x["label"] for x in c["categories"][0]["category"] if not x.get("vline")]
        dates = []
        for lab in labels:
            m, d = map(int, lab.split("/"))
            y = ty + (1 if m < tm else 0)          # labels run from the target month into the next one or two
            dates.append(pd.Timestamp(y, m, d))
        for s in c["dataset"]:
            v = pd.to_numeric(pd.Series([p.get("value") for p in s["data"]][:len(dates)]), errors="coerce")
            ser = pd.Series(v.values, index=dates[:len(v)]).dropna()
            if s["seriesname"].startswith("Actual"):
                if len(ser):
                    actual[(tgt, s["seriesname"])] = float(ser.iloc[-1])
            else:
                paths[(tgt, s["seriesname"])] = ser
    return paths, actual


def target_of(event):                              # KXCPI-26FEB -> '2026-2' (None if the ticker doesn't parse)
    import re
    m = re.search(r"-(\d{2})([A-Z]{3})", event)
    return f"{2000 + int(m.group(1))}-{MON[m.group(2)]}" if m and m.group(2) in MON else None


def dollars(b, f="close"):
    if not b:
        return np.nan
    v = b.get(f"{f}_dollars", b.get(f))
    if v in (None, ""):
        return np.nan
    return float(v) if isinstance(v, str) else float(v) / 100


def main():
    paths, actual = nowcast_paths()
    rows = []
    for series, (name, aname) in SERIES.items():
        # The nowcast's day-before error, on releases before Kalshi listed CPI markets.
        errs = []
        for (tgt, nm), ser in paths.items():
            if nm != name or tuple(map(int, tgt.split("-"))) > (2021, 6) or (tgt, aname) not in actual:
                continue
            if len(ser) >= 2:
                errs.append(actual[(tgt, aname)] - ser.iloc[-2])     # last nowcast before the release day
        sig = float(np.std(errs, ddof=1))
        print(f"{series}: nowcast day-before error sd {sig:.3f} pp over {len(errs)} releases to {SIGMA_END}, mean {np.mean(errs):+.3f}")
        mk = [json.loads(l) for l in gzip.open(os.path.join(KH, f"markets_{series}.jsonl.gz"), "rt")]
        for m in mk:
            if m.get("strike_type") != "greater" or m.get("result") not in ("yes", "no") or m["close_time"][:10] >= FINAL_TEST_START:
                continue
            close = pd.Timestamp(m["close_time"])
            et = close.tz_convert("America/New_York")
            snap = (et.normalize() - pd.offsets.BDay(1) + pd.Timedelta(hours=10, minutes=30)).tz_convert("UTC")
            tgt = target_of(m["event_ticker"])
            ser = paths.get((tgt, name))
            if ser is None:
                continue
            nc = ser[ser.index <= snap.tz_localize(None).normalize()]
            if nc.empty:
                continue
            n = float(nc.iloc[-1])
            p = os.path.join(KH, "candles_60m", series, f"{m['ticker']}.json.gz")
            if not os.path.exists(p):
                continue
            cs = json.load(gzip.open(p, "rt")).get("candlesticks", [])
            cs = [c for c in cs if c["end_period_ts"] <= snap.timestamp()]
            if not cs or snap.timestamp() - cs[-1]["end_period_ts"] > 3 * 3600:
                continue
            bid, ask = dollars(cs[-1].get("yes_bid")), dollars(cs[-1].get("yes_ask"))
            k = float(m["floor_strike"])
            rows.append({"series": series, "event": m["event_ticker"], "date": m["close_time"][:10], "k": k,
                         "bid": bid, "ask": ask, "nowcast": n, "p_now": 1 - norm.cdf((k + 0.05 - n) / sig),
                         "y": 1.0 if m["result"] == "yes" else 0.0, "actual": pd.to_numeric(str(m.get("expiration_value") or "").rstrip("%"), errors="coerce")})
    d = pd.DataFrame(rows)
    q = d[(d.bid > 0) & (d.ask < 1) & (d.ask > d.bid) & (d.ask - d.bid <= 0.10)].copy()
    q["mid"] = (q.bid + q.ask) / 2
    print(f"\n{len(d)} contract-releases with a quote; {len(q)} quoted within 10c, on {q.event.nunique()} releases "
          f"({q.date.min()} to {q.date.max()})")

    def boot(df, f):
        ev = df.event.unique()
        g = {e: x for e, x in df.groupby("event")}
        return np.percentile([f(pd.concat([g[e] for e in rng.choice(ev, len(ev))])) for _ in range(2000)], [2.5, 97.5])

    for s, g in q.groupby("series"):
        bk, bn = ((g.mid - g.y) ** 2).mean(), ((g.p_now - g.y) ** 2).mean()
        lo, hi = boot(g, lambda x: ((x.mid - x.y) ** 2).mean() - ((x.p_now - x.y) ** 2).mean())
        print(f"\n{s}: Brier Kalshi mid {bk:.4f}, nowcast {bn:.4f}; Kalshi minus nowcast {bk - bn:+.4f} ({lo:+.4f} to {hi:+.4f})"
              f" over {len(g)} contracts, {g.event.nunique()} releases")
        for th in (0.05, 0.10, 0.15):
            buy = g[g.p_now - g.ask > th]
            sell = g[g.bid - g.p_now > th]
            fee = lambda p: np.ceil(np.round(100 * FEE * p * (1 - p) * 100, 6)) / 100 / 100
            pnl = pd.concat([buy.assign(pnl=buy.y - buy.ask - fee(buy.ask)), sell.assign(pnl=sell.bid - sell.y - fee(sell.bid))])
            if len(pnl) < 5:
                print(f"   trade toward the nowcast when it is {100 * th:.0f}c past the touch: {len(pnl)} trades"); continue
            lo, hi = boot(pnl, lambda x: x.pnl.mean())
            print(f"   trade toward the nowcast when it is {100 * th:.0f}c past the touch: {len(pnl)} trades on "
                  f"{pnl.event.nunique()} releases, mean {100 * pnl.pnl.mean():+.1f}c per contract ({100 * lo:+.1f} to {100 * hi:+.1f}), "
                  f"won {(pnl.pnl > 0).mean():.0%}")
    q.to_csv(os.path.join(ROOT, "research", "output", "explore_cpi.csv"), index=False)


if __name__ == "__main__":
    main()
