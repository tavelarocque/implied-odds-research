"""EXPLORATORY: do Kalshi's hourly Bitcoin contracts lag the spot price, and would trading toward spot pay after fees?

Development sample only: 400 hourly KXBTCD sets settling before FINAL_TEST_START, chosen at random (seed 13) by
collect/btc_stale_data.py. Looks for a hypothesis, tests nothing.

Fair value: for each minute t from 55 to 3 minutes before the hour, the probability that Bitcoin finishes above K,
from Coinbase's BTC-USD price at t and a lognormal move over the time left, with volatility measured from 1-minute
returns over the 6 hours before the set opened (so nothing inside the hour is used to set it). Kalshi settles on a
60-second average of CF Benchmarks' index; the last 2 minutes are left out and the small difference is ignored.
Kalshi: yes bid and ask from the last 1-minute candle at or before t, quoted with a spread of at most 10 cents.

Reported:
  1. Is the spot model a fair benchmark? Brier of the model vs Kalshi's mid at 30 minutes before the hour.
  2. How far apart they are: mean |model - mid| by minutes to settlement.
  3. Trading toward the model: the first minute a contract's model value is more than 5, 10 or 20 cents past the touch,
     buy or sell 1 contract at the touch, hold to settlement, Kalshi's taker fee. Mean profit per contract, 95% interval
     from 2,000 resamples of whole sets, hit rate. Three thresholds, fixed here.
"""
import gzip, json, math, os
import numpy as np
import pandas as pd
from scipy.stats import norm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KH = os.path.join(ROOT, "data", "history", "kalshi")
CB = os.path.join(ROOT, "data", "history", "crypto", "coinbase_1m")
YEAR_MIN = 365 * 24 * 60
FEE = 0.07
rng = np.random.default_rng(14)


def dollars(b, f="close"):
    if not b:
        return np.nan
    v = b.get(f"{f}_dollars", b.get(f))
    if v in (None, ""):
        return np.nan
    return float(v) if isinstance(v, str) else float(v) / 100


def fee(p):
    return np.ceil(np.round(100 * FEE * p * (1 - p) * 100, 6)) / 100 / 100


def main():
    ms = [json.loads(l) for l in gzip.open(os.path.join(KH, "markets_KXBTCD_sample.jsonl.gz"), "rt")]
    by_ev = {}
    for m in ms:
        by_ev.setdefault(m["event_ticker"], []).append(m)
    rows = []
    for ev, em in by_ev.items():
        cbp = os.path.join(CB, f"{ev}.json")
        if not os.path.exists(cbp):
            continue
        cb = pd.DataFrame(json.load(open(cbp)), columns=["t", "low", "high", "open", "close", "vol"])
        if len(cb) < 300:
            continue
        spot = pd.Series(cb.close.values, index=cb.t.values + 60)       # stamped at the minute's end
        close_ts = int(pd.Timestamp(em[0]["close_time"]).timestamp())
        open_ts = close_ts - 3600
        pre = spot[(spot.index > open_ts - 6 * 3600) & (spot.index <= open_ts)]
        r = np.diff(np.log(pre.values))
        if len(r) < 200:
            continue
        sig = r.std() * math.sqrt(YEAR_MIN)
        grid = np.arange(close_ts - 55 * 60, close_ts - 3 * 60 + 1, 60)
        S = spot.reindex(grid, method="ffill").values
        for m in em:
            if m.get("result") not in ("yes", "no") or m.get("strike_type") not in ("greater", "greater_or_equal"):
                continue
            p = os.path.join(KH, "candles_1m", "KXBTCD", f"{m['ticker']}.json.gz")
            if not os.path.exists(p):
                continue
            cs = json.load(gzip.open(p, "rt")).get("candlesticks", [])
            if not cs:
                continue
            ct = np.array([c["end_period_ts"] for c in cs])
            bid = pd.Series([dollars(c.get("yes_bid")) for c in cs], index=ct).ffill()
            ask = pd.Series([dollars(c.get("yes_ask")) for c in cs], index=ct).ffill()
            K = float(m["floor_strike"])
            tleft = (close_ts - grid) / 60 / YEAR_MIN
            sd = sig * np.sqrt(tleft)
            fair = norm.cdf((np.log(S / K) - sd ** 2 / 2) / sd)
            b, a = bid.reindex(grid, method="ffill").values, ask.reindex(grid, method="ffill").values
            y = 1.0 if m["result"] == "yes" else 0.0
            for j, t in enumerate(grid):
                rows.append((ev, m["ticker"], int((close_ts - t) / 60), K, S[j], sig, fair[j], b[j], a[j], y))
    d = pd.DataFrame(rows, columns=["event", "ticker", "mins_left", "K", "spot", "sig", "fair", "bid", "ask", "y"])
    q = d[(d.bid > 0) & (d.ask < 1) & (d.ask > d.bid) & (d.ask - d.bid <= 0.10) & d.fair.notna()].copy()
    q["mid"] = (q.bid + q.ask) / 2
    print(f"{d.event.nunique()} sets, {d.ticker.nunique()} contracts, {len(q):,} quoted contract-minutes "
          f"(median annualized vol from the 6 hours before: {d.drop_duplicates('event').sig.median():.0%})")

    t30 = q[q.mins_left == 30]
    bk, bm = ((t30.mid - t30.y) ** 2).mean(), ((t30.fair - t30.y) ** 2).mean()
    print(f"\n1. Benchmark check, 30 minutes out ({len(t30)} contracts): Brier Kalshi mid {bk:.4f}, spot model {bm:.4f}")
    print("\n2. Mean |model - Kalshi mid| by minutes to settlement:")
    q["gap"] = (q.fair - q.mid).abs()
    print("   " + ", ".join(f"{lo}-{hi} min: {100 * q[(q.mins_left >= lo) & (q.mins_left <= hi)].gap.mean():.1f}c"
                            for lo, hi in ((46, 55), (31, 45), (16, 30), (3, 15))))

    print("\n3. Trading toward the model at the touch (first signal per contract, 1 contract, after taker fee):")
    for th in (0.05, 0.10, 0.20):
        tr = []
        for tk, g in q.sort_values("mins_left", ascending=False).groupby("ticker"):
            s = g[(g.fair - g.ask > th) | (g.bid - g.fair > th)]
            if s.empty:
                continue
            r = s.iloc[0]
            if r.fair - r.ask > th:
                tr.append((r.event, "buy", r.mins_left, r.y - r.ask - fee(r.ask)))
            else:
                tr.append((r.event, "sell", r.mins_left, r.bid - r.y - fee(r.bid)))
        t = pd.DataFrame(tr, columns=["event", "side", "mins_left", "pnl"])
        if len(t) < 10:
            print(f"   {100 * th:.0f}c: {len(t)} trades"); continue
        g = t.groupby("event").pnl.agg(["sum", "count"]).values
        w = rng.multinomial(len(g), np.full(len(g), 1 / len(g)), size=2000) @ g
        lo, hi = np.percentile(w[:, 0] / w[:, 1], [2.5, 97.5])
        print(f"   {100 * th:.0f}c past the touch: {len(t)} trades in {t.event.nunique()} sets, mean {100 * t.pnl.mean():+.2f}c "
              f"per contract ({100 * lo:+.2f} to {100 * hi:+.2f}), won {(t.pnl > 0).mean():.0%}, "
              f"median {t.mins_left.median():.0f} min before the hour")
    q.to_csv(os.path.join(ROOT, "research", "output", "explore_btc_stale.csv.gz"), index=False)


if __name__ == "__main__":
    main()
