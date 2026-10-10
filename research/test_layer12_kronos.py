"""Layer 12, pre-registered in research/PREREGISTRATION_LAYER12.md: Kronos-small as a forecaster of Kalshi's 5pm
Bitcoin contracts, development data settling 2025-09-01 to 2026-03-31. Read the pre-registration first; nothing here
may differ from it.

Needs torch and the Kronos repository (KRONOS_DIR, default ~/CODE/Kronos), so it runs in its own environment:
    ~/CODE/kronos-venv/bin/python research/test_layer12_kronos.py paths    # sample Kronos paths (resumable cache)
    ~/CODE/kronos-venv/bin/python research/test_layer12_kronos.py score    # the verdict and the secondary results
"""
import gzip, json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research"))
from config import FINAL_TEST_START
from explore_cpi_corp import corp, brier

KH = os.path.join(ROOT, "data", "history", "kalshi")
OUT = os.path.join(ROOT, "research", "output")
CACHE = os.path.join(OUT, "layer12_kronos_paths.npz")
START, END = "2025-09-01", "2026-03-31"
HORIZONS, N_PATHS, CONTEXT, BAND = (1, 3), 200, 512, 0.06
assert END < FINAL_TEST_START
logit = lambda p: np.log(p / (1 - p))


def dollars(b, f="close"):
    if not b:
        return np.nan
    v = b.get(f"{f}_dollars", b.get(f))
    if v in (None, ""):
        return np.nan
    return float(v) if isinstance(v, str) else float(v) / 100


def coinbase():
    cb = pd.read_csv(os.path.join(ROOT, "data", "history", "crypto", "coinbase_1h.csv")).sort_values("t")
    return cb.drop_duplicates("t").set_index("t")


def markets():
    rows = []
    for l in gzip.open(os.path.join(KH, "markets_KXBTCD_5pm.jsonl.gz"), "rt"):
        m = json.loads(l)
        if not m["event_ticker"].endswith("17") or m.get("strike_type") != "greater" or m.get("result") not in ("yes", "no"):
            continue
        close, opened = pd.Timestamp(m["close_time"]), pd.Timestamp(m.get("open_time") or m["close_time"])
        if not (START <= m["close_time"][:10] <= END) or close - opened < pd.Timedelta(hours=2):
            continue
        rows.append({"ticker": m["ticker"], "day": m["close_time"][:10], "end": int(close.timestamp()),
                     "k": float(m["floor_strike"]), "y": 1.0 if m["result"] == "yes" else 0.0})
    return pd.DataFrame(rows)


def context(cb, quote_ts):
    """The CONTEXT hourly candles fully closed by quote_ts (Coinbase t = the candle's start)."""
    x = cb[cb.index + 3600 <= quote_ts].iloc[-CONTEXT:]
    assert len(x) == CONTEXT and x.index[-1] + 3600 == quote_ts, "missing Coinbase candles before the quote"
    return x


def sample_paths():
    import torch
    sys.path.insert(0, os.path.expanduser(os.environ.get("KRONOS_DIR", "~/CODE/Kronos")))
    from model import Kronos, KronosTokenizer, KronosPredictor
    tok = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
    mdl = Kronos.from_pretrained("NeoQuasar/Kronos-small")
    # Amendment 1 (pre-registration): Apple GPU ("mps"), 200 paths drawn as 8 batches of 25. CPU took about 0.25 s
    # per path, roughly 12 hours for the whole window; 200 at once runs out of GPU memory and 50
    # stalls 3 hours out on this 8 GB Mac.
    pred = KronosPredictor(mdl, tok, device=os.environ.get("KRONOS_DEVICE", "mps"), max_context=CONTEXT)
    cb, mk = coinbase(), markets()
    done = dict(np.load(CACHE)) if os.path.exists(CACHE) else {}
    days = sorted(mk.groupby("day").end.first().items())
    print(f"{len(days)} settlement days, {len(done)} day-horizons cached", flush=True)
    for n, (day, end) in enumerate(days):
        for h in HORIZONS:
            key = f"{day}_{h}"
            if key in done:
                continue
            torch.manual_seed(12); np.random.seed(12)
            x = context(cb, end - h * 3600)
            df = x[["open", "high", "low", "close"]].assign(volume=x.vol).reset_index(drop=True)
            xt = pd.Series(pd.to_datetime(x.index, unit="s"))
            yt = pd.Series(pd.to_datetime([end - (h - i) * 3600 for i in range(h)], unit="s"))
            fin = []
            for _ in range(N_PATHS // 25):
                out = pred.predict_batch([df] * 25, [xt] * 25, [yt] * 25, pred_len=h,
                                         T=1.0, top_k=0, top_p=0.9, sample_count=1, verbose=False)
                fin += [o["close"].values[-1] for o in out]
            done[key] = np.array(fin)
        if n % 10 == 0 or n == len(days) - 1:
            np.savez(CACHE, **done)
            print(f"  {n + 1} of {len(days)} days", flush=True)
    np.savez(CACHE, **done)


def quotes(cb, mk, paths):
    rows = []
    for r in mk.itertuples():
        p = os.path.join(KH, "candles_60m", "KXBTCD", f"{r.ticker}.json.gz")
        cs = json.load(gzip.open(p, "rt")).get("candlesticks", []) if os.path.exists(p) else []
        t = np.array([c["end_period_ts"] for c in cs])
        for h in HORIZONS:
            qt = r.end - h * 3600
            x = cb[cb.index + 3600 <= qt].iloc[-24:]
            spot = float(x.close.iloc[-1])
            if abs(r.k / spot - 1) > BAND:
                continue
            rec = {"day": r.day, "h": h, "k": r.k, "y": r.y, "spot": spot, "ticker": r.ticker, "in_file": len(cs) > 0}
            i = np.searchsorted(t, qt, side="right") - 1 if len(cs) else -1
            if i >= 0 and qt - t[i] <= 3600:
                b, a = dollars(cs[i].get("yes_bid")), dollars(cs[i].get("yes_ask"))
                if b > 0 and a < 1 and a > b and a - b <= 0.10:
                    rec["mid"] = (a + b) / 2
            fin = paths[f"{r.day}_{h}"]
            rec["kronos"] = float((fin > r.k).mean())
            r24 = np.diff(np.log(x.close.values))
            vol = r24.std(ddof=1) * np.sqrt(h)
            from math import erf, sqrt, log
            rec["lognormal"] = 0.5 * (1 + erf((log(spot / r.k)) / (vol * sqrt(2))))
            rec["er"] = abs(x.close.iloc[-1] - x.open.iloc[0]) / (x.high.max() - x.low.min())
            rec["kr_sd"] = float(np.std(np.log(fin / spot)))
            rows.append(rec)
    return pd.DataFrame(rows)


def logit_fit(A, y, iters=60):
    w = np.zeros(A.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-A @ w)); W = p * (1 - p) + 1e-9
        step = np.linalg.solve(A.T @ (A * W[:, None]), A.T @ (y - p)); w += step
        if np.abs(step).max() < 1e-9:
            break
    return w


def day_boot(x, stat, B=2000, seed=0):
    rng = np.random.default_rng(seed)
    days = x.day.unique(); g = {d: np.where(x.day.values == d)[0] for d in days}
    return np.array([stat(x.iloc[np.concatenate([g[d] for d in rng.choice(days, len(days))])]) for _ in range(B)])


def score():
    cb, mk = coinbase(), markets()
    paths = dict(np.load(CACHE))
    q = quotes(cb, mk, paths)
    q.to_csv(os.path.join(OUT, "layer12_kronos.csv.gz"), index=False)
    miss = (~q.in_file).sum()
    q = q.dropna(subset=["mid"])
    print(f"Layer 12, Kronos-small vs Kalshi, 5pm Bitcoin sets settling {START} to {END}")
    print(f"{len(q)} quoted contract-horizons on {q.day.nunique()} days ({miss} strikes in the band had no candles)\n")
    out = []
    for h in HORIZONS:
        x = q[q.h == h].reset_index(drop=True)
        d = lambda s: (brier(s.kronos.values, s.y.values) - brier(s["mid"].values, s.y.values)).mean()
        est, bs = d(x), day_boot(x, d, seed=h)
        lo, hi = np.percentile(bs, [1.25, 98.75])
        verdict = "Kronos beats Kalshi" if hi < 0 else ("Kalshi beats Kronos" if lo > 0 else "no difference shown")
        p = 2 * min((bs >= 0).mean(), (bs <= 0).mean())
        print(f"{h}h before settlement: {len(x)} contracts, {x.day.nunique()} days")
        print(f"  PRIMARY  Brier Kronos - Kalshi {est:+.5f} (97.5%: {lo:+.5f} to {hi:+.5f}) -> {verdict}")
        out.append(("primary", h, est, lo, hi, p, verdict))
        for name in ("kronos", "mid", "lognormal"):
            c = corp(x[name].values, x.y.values, brier)
            print(f"  {name:<9} Brier {c[0]:.4f} = miscalibration {c[1]:.4f} - discrimination {c[2]:.4f} + uncertainty {c[3]:.4f}")
        def coef(s):
            A = np.column_stack([np.ones(len(s)), logit(s["mid"].clip(.005, .995).values), logit(s.kronos.clip(.005, .995).values)])
            return logit_fit(A, s.y.values)[2]
        b, bs = coef(x), day_boot(x, coef, B=1000, seed=10 + h)
        lo, hi = np.percentile(bs, [2.5, 97.5]); p = 2 * min((bs >= 0).mean(), (bs <= 0).mean())
        print(f"  SECONDARY 1  Kronos coefficient alongside Kalshi's price: {b:+.3f} (95%: {lo:+.3f} to {hi:+.3f})")
        out.append(("secondary1", h, b, lo, hi, p, ""))
        med = q.drop_duplicates(["day", "h"]).query("h == @h").er.median()
        for lab, s in (("choppy (ER below median)", x[x.er < med]), ("trending (ER above median)", x[x.er >= med])):
            bb = day_boot(s, coef, B=1000, seed=20 + h)
            print(f"  SECONDARY 2  {lab}: {s.day.nunique()} days, Kronos coefficient {coef(s):+.3f} "
                  f"({np.percentile(bb, 2.5):+.3f} to {np.percentile(bb, 97.5):+.3f}); Brier Kronos - Kalshi {d(s):+.5f}")
        dd = x.drop_duplicates("day").merge(mk.drop_duplicates("day")[["day", "end"]], on="day")
        settle = cb.close.reindex(dd.end.values - 3600).values
        real = np.log(settle / dd.spot.values)
        print(f"  Kronos 1-sd of the final price {100 * np.sqrt((dd.kr_sd ** 2).mean()):.2f}% (root-mean-square over days) "
              f"vs realized move sd {100 * np.nanstd(real):.2f}%\n")
    pd.DataFrame(out, columns=["test", "h", "est", "lo", "hi", "p", "verdict"]).to_csv(
        os.path.join(OUT, "layer12_kronos_verdict.csv"), index=False)


if __name__ == "__main__":
    {"paths": sample_paths, "score": score}[sys.argv[1]]()
