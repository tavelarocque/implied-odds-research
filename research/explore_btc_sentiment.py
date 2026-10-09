"""EXPLORATORY: Kalshi's 5pm ET Bitcoin contracts (KXBTCD), long-shot overpricing and crypto crowd mood.

Development sample only (contracts settling before FINAL_TEST_START). Looks for a hypothesis, tests nothing.

Step 1, the base effect. Every "BTC above K at 5pm ET" contract is quoted 1, 3 and 6 hours before settlement (last
hourly candle within the hour before, spread at most 10 cents). A long shot is a side priced at 10 cents or less:
YES on a high strike (upside) or NO on a low strike (downside, YES at 90 cents or more). Overpricing = what the long
shot cost at the mid minus how often it paid. Also: selling the long shot at the touch, after Kalshi's taker fee.

Step 2, mood. Ten comparisons, listed here before any result:
  greed (Fear & Greed >= 75, the index's "extreme greed")   -> upside long shots more overpriced      (1h, 3h)
  fear (Fear & Greed <= 25, "extreme fear")                 -> downside long shots more overpriced    (1h, 3h)
  funding in its top fifth (leveraged crowd long)           -> upside long shots more overpriced      (1h, 3h)
  funding in its bottom fifth (crowd short)                 -> downside long shots more overpriced    (1h, 3h)
  Bitcoin Wikipedia views in their top fifth (attention)    -> long shots, both sides, more overpriced (1h, 3h)
Each against all other days. All measures are known before the quote: Fear & Greed is stamped 00:00 UTC of the
settlement day, funding is the mean of the 24 hours ending 6 hours before settlement, Wikipedia is the previous UTC day.
Intervals: 2,000 resamples of whole settlement days.

Run from the project root after:
    python3 collect/kalshi_btc_daily.py     (5pm sets only: markets and the last 7 hours of hourly candles)
    python3 collect/crypto_sentiment.py ; python3 collect/attention_history.py
"""
import gzip, json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research"))
from config import FINAL_TEST_START
KH = os.path.join(ROOT, "data", "history", "kalshi")
ATT = os.path.join(ROOT, "data", "history", "attention")
FEE = 0.07
rng = np.random.default_rng(11)


def dollars(b, f="close"):
    if not b:
        return np.nan
    v = b.get(f"{f}_dollars", b.get(f))
    if v in (None, ""):
        return np.nan
    return float(v) if isinstance(v, str) else float(v) / 100


def fee(p):
    return np.ceil(np.round(100 * FEE * p * (1 - p) * 100, 6)) / 100 / 100


def load_markets():
    keep = []
    for l in gzip.open(os.path.join(KH, "markets_KXBTCD_5pm.jsonl.gz"), "rt"):
        m = json.loads(l)
        if not m["event_ticker"].endswith("17") or m.get("strike_type") != "greater" or m.get("result") not in ("yes", "no"):
            continue
        if m["close_time"][:10] >= FINAL_TEST_START:
            continue
        close, opened = pd.Timestamp(m["close_time"]), pd.Timestamp(m.get("open_time") or m["close_time"])
        if close - opened < pd.Timedelta(hours=2):          # the 5pm set opens a day ahead; hourly sets an hour ahead
            continue
        keep.append({"ticker": m["ticker"], "event": m["event_ticker"], "close": close, "k": float(m["floor_strike"]),
                     "y": 1.0 if m["result"] == "yes" else 0.0})
    return pd.DataFrame(keep)


def quotes(mk):
    rows = []
    for r in mk.itertuples():
        p = os.path.join(KH, "candles_60m", "KXBTCD", f"{r.ticker}.json.gz")
        if not os.path.exists(p):
            continue
        cs = json.load(gzip.open(p, "rt")).get("candlesticks", [])
        if not cs:
            continue
        t = np.array([c["end_period_ts"] for c in cs])
        for h in (1, 3, 6):
            target = r.close.timestamp() - h * 3600
            i = np.searchsorted(t, target, side="right") - 1
            if i < 0 or target - t[i] > 3600:
                continue
            bid, ask = dollars(cs[i].get("yes_bid")), dollars(cs[i].get("yes_ask"))
            rows.append({"ticker": r.ticker, "event": r.event, "day": r.close.strftime("%Y-%m-%d"), "close": r.close,
                         "h": h, "bid": bid, "ask": ask, "y": r.y})
    q = pd.DataFrame(rows)
    q = q[(q.bid > 0) & (q.ask < 1) & (q.ask > q.bid) & (q.ask - q.bid <= 0.10)].copy()
    q["mid"] = (q.bid + q.ask) / 2
    q["side"] = np.where(q.mid <= 0.10, "up", np.where(q.mid >= 0.90, "down", None))
    q = q[q.side.notna()].copy()
    q["over"] = np.where(q.side == "up", q.mid - q.y, q.y - q.mid)            # long shot's price minus its payoff
    q["pnl"] = np.where(q.side == "up", q.bid - q.y - fee(q.bid), q.y - q.ask - fee(q.ask))   # sell the long shot
    return q


def boot_mean(df, col):
    g = df.groupby("day")[col].agg(["sum", "count"]).values
    w = rng.multinomial(len(g), np.full(len(g), 1 / len(g)), size=2000) @ g
    return np.percentile(w[:, 0] / w[:, 1], [2.5, 97.5])


def boot_diff(df, flag, col):
    g = df.groupby("day").apply(lambda x: pd.Series({"s1": x.loc[x[flag], col].sum(), "n1": x[flag].sum(),
                                                       "s0": x.loc[~x[flag], col].sum(), "n0": (~x[flag]).sum()})).values
    t = rng.multinomial(len(g), np.full(len(g), 1 / len(g)), size=2000) @ g
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.nanpercentile(t[:, 0] / t[:, 1] - t[:, 2] / t[:, 3], [2.5, 97.5])


def mood(days):
    fg = pd.read_csv(os.path.join(ATT, "fear_greed_daily.csv")).set_index("date").value
    fr = pd.read_csv(os.path.join(ATT, "binance_funding_btc.csv"))
    fr = pd.Series(fr.funding_rate.values, index=pd.to_datetime(fr.time_utc, utc=True, format="ISO8601")).sort_index()
    wk = pd.read_csv(os.path.join(ATT, "wikipedia_daily.csv"), parse_dates=["date"])
    v = wk[wk.article == "Bitcoin"].set_index("date").views.asfreq("D")
    wiki = np.log(v.shift(1) / v.shift(2).rolling(28, min_periods=20).median())
    out = []
    for day, close in days.items():
        end = close - pd.Timedelta(hours=6)
        f = fr[(fr.index > end - pd.Timedelta(hours=24)) & (fr.index <= end)]
        out.append({"day": day, "fg": fg.get(day, np.nan), "funding": f.mean() if len(f) else np.nan,
                    "wiki": wiki.get(pd.Timestamp(day), np.nan)})
    return pd.DataFrame(out).set_index("day")


def main():
    mk = load_markets()
    q = quotes(mk)
    print(f"KXBTCD 5pm ET sets settling before {FINAL_TEST_START}: {mk.event.nunique()} days, {len(mk)} contracts; "
          f"{len(q)} long-shot quotes on {q.day.nunique()} days ({q.day.min()} to {q.day.max()})")
    print("\nStep 1, base effect (overpricing = long shot's mid minus its payoff; P&L = selling it at the touch after fees):")
    for h in (1, 3, 6):
        for side in ("up", "down"):
            s = q[(q.h == h) & (q.side == side)]
            if len(s) < 20:
                continue
            lo, hi = boot_mean(s, "over"); plo, phi = boot_mean(s, "pnl")
            print(f"  {h}h {side:<4} n {len(s):5d} on {s.day.nunique():4d} days, mean price {100 * (s.mid if side == 'up' else 1 - s.mid).mean():.1f}c, "
                  f"paid {100 * (s.y if side == 'up' else 1 - s.y).mean():.2f}%; overpricing {100 * s.over.mean():+.2f}c ({100 * lo:+.2f} to {100 * hi:+.2f}); "
                  f"selling it {100 * s.pnl.mean():+.2f}c ({100 * plo:+.2f} to {100 * phi:+.2f})")
    m = mood(q.groupby("day").close.first())
    q = q.join(m, on="day")
    fq = m.funding.quantile([0.2, 0.8]).values; wq = m.wiki.quantile(0.8)
    print(f"\nStep 2, mood (thresholds: funding bottom/top fifth {fq[0]:.5f}/{fq[1]:.5f} per 8h; Wikipedia top fifth {wq:+.2f} log points)")
    tests = [("greed (F&G >= 75)", q.fg >= 75, "up"), ("fear (F&G <= 25)", q.fg <= 25, "down"),
             ("funding top fifth", q.funding >= fq[1], "up"), ("funding bottom fifth", q.funding <= fq[0], "down"),
             ("attention top fifth", q.wiki >= wq, "both")]
    for name, flag, side in tests:
        for h in (1, 3):
            s = q[(q.h == h) & ((q.side == side) if side != "both" else True)].copy()
            s["hi"] = flag.loc[s.index].fillna(False).astype(bool)
            if s.hi.sum() < 10:
                print(f"  {name:<22} {h}h {side:<4} too few ({s.hi.sum()})"); continue
            a, b = s[s.hi].over.mean(), s[~s.hi].over.mean()
            lo, hi = boot_diff(s, "hi", "over")
            print(f"  {name:<22} {h}h {side:<4} overpricing {100 * a:+.2f}c (n {s.hi.sum()}, {s[s.hi].day.nunique()} days) vs "
                  f"other days {100 * b:+.2f}c; difference {100 * (a - b):+.2f}c ({100 * lo:+.2f} to {100 * hi:+.2f})")
    q.to_csv(os.path.join(ROOT, "research", "output", "explore_btc_sentiment.csv"), index=False)


if __name__ == "__main__":
    main()
