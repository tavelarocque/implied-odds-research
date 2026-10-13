"""Builds the data file behind dashboard/index.html (the local Implied Odds exchange screen).

Descriptive only: reads the paper-trade logs and settlements on the data branch, public Coinbase and Deribit prices,
and the layer 13 holdout file; changes no rule, no trade and no pre-registered analysis. Writes
data/dashboard/data.js (git-ignored). Run every 15 minutes by collect/launchd/com.tave.impliedodds.dashboard.plist,
or by hand:  PYTHONPATH=. .venv/bin/python trade/dashboard.py
"""
import json, os, subprocess, sys, time
from datetime import datetime, timezone
import numpy as np, pandas as pd, requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "trade"), os.path.join(ROOT, "research")]
import paper as P

OUT = os.path.join(ROOT, "data", "dashboard")
PT = "America/Vancouver"
LAYERS = [  # key, data-branch log, results, display name, what it does, verdict date
    ("btc5", "paper_btc", "paper_btc_results", "L5 · BTC", "Options vs Kalshi, Bitcoin hourly and daily", "2026-11-30"),
    ("stocks", "paper", "paper_results", "L5 · SPX/NDX", "Options vs Kalshi, S&P and Nasdaq daily ranges", "2026-11-30"),
    ("l13b", "paper_l13", "paper_l13_results", "L13b", "Lognormal blend, 5pm Bitcoin set, 3 h out", "2027-02-01"),
    ("l11", "paper_l11", "paper_l11_results", "L11", "Sell downside long shots on low-funding or fear days", "2027-02-01"),
]
NAMES = {"KXINX": "S&P 500", "KXNASDAQ100": "Nasdaq-100"}


def git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def label(key, t):
    if key == "stocks":
        nm = NAMES.get(t.get("series"), t.get("series", "?"))
        lo, hi = t.get("lo"), t.get("hi")
        rng = f"{lo:,.0f}–{hi:,.0f}" if lo and hi else (f">{lo:,.0f}" if lo else f"<{hi:,.0f}")
        return nm, rng
    k = t.get("kind") or {"l13b": "5pm set", "l11": "5pm set"}.get(key, "")
    return "BTC", f">${t['strike']:,.0f} {k}".strip()


def trades():
    rows = []
    for key, log, res, *_ in LAYERS:
        tr, rs = P.all_trades(log, res)
        for day, ts in tr.items():
            for t in ts:
                r = rs.get(day, {}).get(t["ticker"])
                snap = pd.Timestamp(t["snap"])
                h = t.get("hours_to_close")
                settle_t = snap + pd.Timedelta(hours=float(h)) if h is not None else pd.Timestamp(f"{day}T20:00:00Z")
                ref = t.get("p_opt", t.get("p_blend"))
                inst, what = label(key, t)
                rows.append(dict(layer=key, snap=snap.isoformat(), settle=settle_t.isoformat(), inst=inst, what=what,
                                 strike=t.get("strike"), side=t["side"], price=t["price"], qty=t["qty"], fee=t["fee"],
                                 ref=None if ref is None else round(float(ref), 4),
                                 capital=t.get("capital"), result=r if r in ("yes", "no") else None,
                                 pnl=round(P.pnl_of(t, r), 2) if r in ("yes", "no") else None,
                                 committee=t.get("committee_take"), p_meta=t.get("p_meta"),
                                 mid=(t["bid"] + t["ask"]) / 2 if "bid" in t else None))
    rows.sort(key=lambda r: r["snap"])
    return rows


def market():
    now = int(time.time()) // 3600 * 3600
    start = now - 46 * 86400
    cb, t0 = [], start
    while t0 < now:
        t1 = min(t0 + 300 * 3600, now)
        cb += requests.get("https://api.exchange.coinbase.com/products/BTC-USD/candles",
                           params={"granularity": 3600, "start": t0, "end": t1}, timeout=30).json()
        t0 = t1; time.sleep(0.25)
    c = pd.DataFrame(cb, columns=["t", "low", "high", "open", "close", "vol"]).drop_duplicates("t").sort_values("t").set_index("t")
    rv = np.log(c.close).diff().rolling(24).std() * np.sqrt(24 * 365) * 100
    dv = requests.get("https://www.deribit.com/api/v2/public/get_volatility_index_data",
                      params={"currency": "BTC", "start_timestamp": start * 1000, "end_timestamp": int(time.time()) * 1000,
                              "resolution": 3600}, timeout=30).json()["result"]["data"]
    dv = pd.Series({int(x[0] // 1000): x[4] for x in dv}).sort_index()
    j = pd.concat([dv.rename("iv"), rv.rename("rv"), c.close.rename("px")], axis=1)
    j = j[j.index >= now - 45 * 86400]
    iso = lambda i: pd.Timestamp(i, unit="s", tz="UTC").isoformat()
    v = j.dropna(subset=["iv", "rv"])
    last7 = c[c.index >= now - 7 * 86400]
    spot = requests.get("https://api.exchange.coinbase.com/products/BTC-USD/ticker", timeout=15).json()
    return {"vol": {"t": [iso(i) for i in v.index], "iv": v.iv.round(2).tolist(), "rv": v.rv.round(2).tolist()},
            "px": {"t": [iso(i) for i in last7.index], "o": last7.open.tolist(), "h": last7.high.tolist(),
                   "l": last7.low.tolist(), "c": last7.close.tolist()},
            "spot": float(spot.get("price", c.close.iloc[-1])), "dvol": float(dv.iloc[-1]),
            "rv_now": round(float(rv.dropna().iloc[-1]), 2),
            "px_24h": float(c.close.iloc[-25]) if len(c) > 25 else None}


def health(rows):
    """Same drift monitor and head-to-head Brier as paper.drift_monitor, kept as series for charting."""
    s = [r for r in rows if r["layer"] in ("btc5", "stocks") and r["result"] and r["ref"] is not None and r["mid"] is not None]
    s.sort(key=lambda r: r["settle"])
    if len(s) < 5:
        return None
    y = np.array([1.0 if r["result"] == "yes" else 0.0 for r in s]); p = np.array([r["ref"] for r in s])
    m = np.array([r["mid"] for r in s]); sc = np.abs(y - p)
    a, errs, alpha, gamma = 0.2, [], 0.2, 0.05
    for i in range(len(sc)):
        prev = sc[:i]
        q = np.inf if (a <= 0 or len(prev) == 0) else (-np.inf if a >= 1 else np.quantile(prev, 1 - a))
        e = float(sc[i] > q); errs.append(e); a += gamma * (alpha - e)
    roll = pd.Series(errs).rolling(20, min_periods=10).mean()
    n = np.arange(1, len(s) + 1)
    return {"t": [r["settle"] for r in s], "miss20": [None if np.isnan(x) else round(float(x), 3) for x in roll],
            "brier_opt": (np.cumsum((p - y) ** 2) / n).round(4).tolist(),
            "brier_mid": (np.cumsum((m - y) ** 2) / n).round(4).tolist(),
            "band": round(alpha + 2 * np.sqrt(alpha * (1 - alpha) / 20), 3)}


def reliability():
    f = os.path.join(ROOT, "research/output/layer13_A.csv.gz")
    if not os.path.exists(f):
        return None
    d = pd.read_csv(f); d = d[d.h == 3]
    edges = [0, .03, .1, .2, .35, .5, .65, .8, .9, .97, 1.0001]
    out = {"n": len(d), "days": int(d.day.nunique())}
    for col in ("mid", "lognormal", "combo"):
        g = d.groupby(pd.cut(d[col], edges, right=False), observed=True).agg(p=(col, "mean"), y=("y", "mean"), n=("y", "size"))
        out[col] = {"p": g.p.round(4).tolist(), "y": g.y.round(4).tolist(), "n": g.n.tolist(),
                    "brier": round(float(((d[col] - d.y) ** 2).mean()), 5)}
    return out


def pipeline():
    log = git("log", "origin/data", "--since=8 days ago", "--format=%cI|%s")
    runs = []
    for line in log.splitlines():
        ts, msg = line.split("|", 1)
        kind = "crypto" if msg.startswith("crypto") else ("stocks" if msg.startswith("snapshot") else None)
        if kind:
            runs.append((pd.Timestamp(ts).tz_convert(PT), kind))
    days = {}
    for t, k in runs:
        days.setdefault(t.strftime("%Y-%m-%d"), {"crypto": 0, "stocks": 0})[k] += 1
    last = {k: max((t for t, kk in runs if kk == k), default=None) for k in ("crypto", "stocks")}
    return {"days": dict(sorted(days.items())), "last": {k: v.isoformat() if v is not None else None for k, v in last.items()}}


def main():
    git("fetch", "-q", "origin", "+refs/heads/data:refs/remotes/origin/data")
    rows = trades()
    out = {"built": datetime.now(timezone.utc).isoformat(),
           "layers": [dict(key=k, name=n, desc=d, verdict=v) for k, _, _, n, d, v in LAYERS],
           "trades": rows, "health": health(rows), "rel": reliability(), "pipeline": pipeline()}
    try:
        out["market"] = market()
    except Exception as e:  # keep the screen up when an exchange API hiccups
        out["market"] = None; out["market_error"] = str(e)[:200]
    try:
        l11 = P.l11_runs()
        out["l11_runs"] = [{k: r.get(k) for k in ("day", "fear_greed", "funding", "signal", "new_trades")} for r in l11[-30:]]
    except Exception:
        out["l11_runs"] = []
    os.makedirs(OUT, exist_ok=True)
    tmp = os.path.join(OUT, "data.js.tmp")
    with open(tmp, "w") as f:
        f.write("window.IO_DATA = " + json.dumps(out, separators=(",", ":"), default=str) + ";\n")
    os.replace(tmp, os.path.join(OUT, "data.js"))
    settled = [r for r in rows if r["pnl"] is not None]
    print(f"dashboard: {len(rows)} trades, {len(settled)} settled, net ${sum(r['pnl'] for r in settled):+.2f}; "
          f"market {'ok' if out['market'] else 'unavailable'} -> data/dashboard/data.js")


if __name__ == "__main__":
    main()
