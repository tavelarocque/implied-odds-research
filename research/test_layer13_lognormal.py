"""Layer 13, pre-registered in research/PREREGISTRATION_LAYER13.md: Kalshi's 5pm Bitcoin price, de-compressed with a
plain lognormal model of the spot price, vs Kalshi's price alone. Read the pre-registration first; nothing here may
differ from it. Needs only numpy and pandas.

    python3 research/test_layer13_lognormal.py dev                    # reproduces the frozen fit's sample (no test)
    UNLOCK_HOLDOUT=1 python3 research/test_layer13_lognormal.py A     # test A, the holdout, run once
    python3 research/test_layer13_lognormal.py B                      # test B, forward, on or after 2027-02-01
"""
import gzip, json, math, os, sys
from datetime import date
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research"))
from config import FINAL_TEST_START
from explore_cpi_corp import corp, brier

KH = os.path.join(ROOT, "data", "history", "kalshi")
OUT = os.path.join(ROOT, "research", "output")
WINDOWS = {"dev": ("2025-09-01", "2026-03-31"), "A": ("2026-04-01", "2026-09-30"), "B": ("2026-10-15", "2027-01-31")}
HORIZONS, BAND, MARGIN, FEE = (1, 3), 0.06, 0.03, 0.07
# Frozen on the development window (2025-09-01 to 2026-03-31, research/output/layer12_kronos.csv.gz), no intercept:
#   logit P = b * logit(Kalshi mid) + c * logit(lognormal)
COEF = {1: (0.794, 0.414), 3: (0.846, 0.432)}
logit = lambda p: np.log(np.clip(p, .005, .995) / (1 - np.clip(p, .005, .995)))


def dollars(b, f="close"):
    if not b:
        return np.nan
    v = b.get(f"{f}_dollars", b.get(f))
    if v in (None, ""):
        return np.nan
    return float(v) if isinstance(v, str) else float(v) / 100


def fee(p):
    """Kalshi taker fee per contract, 0.07 x P x (1 - P) rounded up to the cent per 100-contract order."""
    return np.ceil(np.round(100 * FEE * p * (1 - p) * 100, 6)) / 100 / 100


def markets(start, end):
    rows = []
    for l in gzip.open(os.path.join(KH, "markets_KXBTCD_5pm.jsonl.gz"), "rt"):
        m = json.loads(l)
        if not m["event_ticker"].endswith("17") or m.get("strike_type") != "greater" or m.get("result") not in ("yes", "no"):
            continue
        close, opened = pd.Timestamp(m["close_time"]), pd.Timestamp(m.get("open_time") or m["close_time"])
        if not (start <= m["close_time"][:10] <= end) or close - opened < pd.Timedelta(hours=2):
            continue
        rows.append({"ticker": m["ticker"], "day": m["close_time"][:10], "end": int(close.timestamp()),
                     "k": float(m["floor_strike"]), "y": 1.0 if m["result"] == "yes" else 0.0})
    return pd.DataFrame(rows)


def quotes(start, end):
    cb = pd.read_csv(os.path.join(ROOT, "data", "history", "crypto", "coinbase_1h.csv")).sort_values("t")
    cb = cb.drop_duplicates("t").set_index("t")
    rows, missing = [], 0
    for r in markets(start, end).itertuples():
        p = os.path.join(KH, "candles_60m", "KXBTCD", f"{r.ticker}.json.gz")
        cs = json.load(gzip.open(p, "rt")).get("candlesticks", []) if os.path.exists(p) else []
        t = np.array([c["end_period_ts"] for c in cs])
        for h in HORIZONS:
            qt = r.end - h * 3600
            x = cb[cb.index + 3600 <= qt].iloc[-24:]
            if len(x) < 24 or x.index[-1] + 3600 != qt:          # no Coinbase candle for the quote hour: left out
                continue
            spot = float(x.close.iloc[-1])
            if abs(r.k / spot - 1) > BAND:
                continue
            if not len(cs):
                missing += 1
                continue
            i = np.searchsorted(t, qt, side="right") - 1
            if i < 0 or qt - t[i] > 3600:
                continue
            b, a = dollars(cs[i].get("yes_bid")), dollars(cs[i].get("yes_ask"))
            if not (b > 0 and a < 1 and a > b and a - b <= 0.10):
                continue
            vol = np.diff(np.log(x.close.values)).std(ddof=1) * math.sqrt(h)
            ln = 0.5 * (1 + math.erf(math.log(spot / r.k) / (vol * math.sqrt(2))))
            mid = (a + b) / 2
            bc, cc = COEF[h]
            combo = 1 / (1 + math.exp(-(bc * logit(mid) + cc * logit(ln))))
            rows.append({"day": r.day, "h": h, "k": r.k, "y": r.y, "bid": b, "ask": a, "mid": mid, "lognormal": ln,
                         "combo": combo})
    return pd.DataFrame(rows), missing


def day_boot(x, stat, B=2000, seed=0):
    rng = np.random.default_rng(seed)
    days = x.day.unique(); g = {d: np.where(x.day.values == d)[0] for d in days}
    return np.array([stat(x.iloc[np.concatenate([g[d] for d in rng.choice(days, len(days))])]) for _ in range(B)])


def main(which):
    start, end = WINDOWS[which]
    if which == "A":
        assert os.environ.get("UNLOCK_HOLDOUT") == "1", "test A reads the holdout: set UNLOCK_HOLDOUT=1, once"
    elif which == "B":
        assert date.today().isoformat() >= "2027-02-01", "test B is analysed on or after 2027-02-01"
    else:
        assert end < FINAL_TEST_START
    q, missing = quotes(start, end)
    q.to_csv(os.path.join(OUT, f"layer13_{which}.csv.gz"), index=False)
    print(f"Layer 13, test {which}: 5pm Bitcoin sets settling {start} to {end}")
    print(f"{len(q)} quoted contract-horizons on {q.day.nunique()} days; {missing} strikes in the band had no candles\n")
    out = []
    for h in HORIZONS:
        x = q[q.h == h].reset_index(drop=True)
        d = lambda s, m="combo": (brier(s[m].values, s.y.values) - brier(s["mid"].values, s.y.values)).mean()
        est, bs = d(x), day_boot(x, d, seed=h)
        lo, hi = np.percentile(bs, [1.25, 98.75])
        verdict = "combination beats Kalshi" if hi < 0 else ("Kalshi beats the combination" if lo > 0 else "no difference shown")
        p = 2 * min((bs >= 0).mean(), (bs <= 0).mean())
        print(f"{h}h before settlement: {len(x)} contracts on {x.day.nunique()} days")
        print(f"  PRIMARY  Brier combination - Kalshi {est:+.5f} (97.5%: {lo:+.5f} to {hi:+.5f}) -> {verdict}")
        out.append((which, "primary", h, est, lo, hi, p, verdict))
        e2, b2 = d(x, "lognormal"), day_boot(x, lambda s: d(s, "lognormal"), seed=10 + h)
        print(f"  SECONDARY  Brier lognormal alone - Kalshi {e2:+.5f} (95%: {np.percentile(b2, 2.5):+.5f} to {np.percentile(b2, 97.5):+.5f})")
        out.append((which, "lognormal", h, e2, np.percentile(b2, 2.5), np.percentile(b2, 97.5), 2 * min((b2 >= 0).mean(), (b2 <= 0).mean()), ""))
        for m in ("combo", "mid", "lognormal"):
            c = corp(x[m].values, x.y.values, brier)
            print(f"  {m:<9} Brier {c[0]:.4f} = miscalibration {c[1]:.4f} - discrimination {c[2]:.4f} + uncertainty {c[3]:.4f}")
        yes = x.combo - x.ask - fee(x.ask) > MARGIN
        no = (x.bid - x.combo) - fee(1 - x.bid) > MARGIN
        pnl = pd.concat([(x.y - x.ask - fee(x.ask))[yes], ((1 - x.y) - (1 - x.bid) - fee(1 - x.bid))[no]])
        tr = pd.DataFrame({"day": x.day[pnl.index].values, "pnl": pnl.values})
        if len(tr):
            bb = day_boot(tr, lambda s: s.pnl.mean(), seed=20 + h)
            print(f"  DESCRIPTION  trading toward the combination at the touch (edge > 3c after fee): {len(tr)} trades on "
                  f"{tr.day.nunique()} days, {100 * tr.pnl.mean():+.2f}c per contract "
                  f"({100 * np.percentile(bb, 2.5):+.2f} to {100 * np.percentile(bb, 97.5):+.2f})")
        print()
    pd.DataFrame(out, columns=["test", "stat", "h", "est", "lo", "hi", "p", "verdict"]).to_csv(
        os.path.join(OUT, f"layer13_{which}_verdict.csv"), index=False)


if __name__ == "__main__":
    main(sys.argv[1])
