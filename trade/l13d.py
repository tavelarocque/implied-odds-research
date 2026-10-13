"""Layer 13d (research/PREREGISTRATION_LAYER13D.md): a shadow layer 13 with hour-of-week volatility. Logging only.

At every hourly crypto run, for every KXBTCD "above" contract within 6% of spot that settles 0.5 to 3.5 hours later and
passes layer 13's quote filter (bid > 0, ask < 1, spread <= 10c), log layer 13's probability and 13d's, which differs
only in the variance: seasonal factors s(h) over 48 buckets (UTC hour x weekday/weekend) from the trailing 90 days of
hourly Coinbase returns, base variance = mean r^2 / s(h) over the last 24 completed hours, forecast variance = base x
the sum of s(h) over the hours to settlement. The blend weights are layer 13's, frozen. Writes data/raw/paper_l13d/.
"""
import gzip, json, math, os, sys
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "research")]
import options_vs_kalshi as L5
RAW = os.path.join(ROOT, "data", "raw")
B, C = 0.846, 0.432                                    # layer 13's frozen blend
H_MIN, H_MAX, NEAR = 0.5, 3.5, 0.06


def bucket(ts):
    """0..47: UTC hour, +24 on Saturday/Sunday."""
    return ts.hour + (24 if ts.dayofweek >= 5 else 0)


def coinbase_hourly(end, hours):
    sys.path.insert(0, os.path.join(ROOT, "collect"))
    from common import get_json
    rows, t1 = [], end
    while (end - t1).total_seconds() / 3600 < hours:
        t0 = t1 - pd.Timedelta(hours=300)
        rows += get_json("https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=3600"
                         f"&start={t0.isoformat()}&end={t1.isoformat()}", retries=3)
        t1 = t0
    c = pd.DataFrame(rows, columns=["t", "low", "high", "open", "close", "vol"]).drop_duplicates("t").sort_values("t")
    c = c[c.t + 3600 <= end.timestamp()]
    c.index = pd.to_datetime(c.t, unit="s", utc=True)
    return c[c.index >= end - pd.Timedelta(hours=hours)]


def forecast_inputs(now):
    """Spot (last completed hourly close), layer 13's sigma (std of the 23 returns in the last 24 candles), 13d's base
    variance and seasonal factors. None if the last 24 hours are incomplete."""
    end = now.floor("h")
    c = coinbase_hourly(end, 90 * 24 + 1)
    r = np.log(c.close).diff().dropna()
    r = r[r.index.to_series().diff().dt.total_seconds().fillna(3600) == 3600]     # consecutive hours only
    last24 = c.tail(24)
    if len(last24) < 24 or last24.index[-1] + pd.Timedelta(hours=1) != end:
        return None
    sigma13 = float(np.diff(np.log(last24.close.values)).std(ddof=1))
    b = r.index.map(bucket)          # Coinbase stamps candles by start time, so the return at t covers [t, t+1h)
    sq = pd.Series(r.values ** 2, index=b)
    s = (sq.groupby(level=0).mean() / sq.mean()).reindex(range(48)).fillna(1.0)
    rec = r[r.index >= end - pd.Timedelta(hours=24)]
    rb = [bucket(ts) for ts in rec.index]
    base = float(np.mean(rec.values ** 2 / s.loc[rb].values))
    return float(c.close.iloc[-1]), sigma13, base, s, end


def seasonal_var(base, s, start, close):
    """base x sum of s(h) over [start, close), the last hour weighted by its fraction."""
    v, t = 0.0, start
    while t < close:
        frac = min(1.0, (close - t).total_seconds() / 3600)
        v += s.loc[bucket(t)] * frac
        t += pd.Timedelta(hours=1)
    return base * v


def lg(p):
    p = min(max(p, .005), .995)
    return math.log(p / (1 - p))


def p_above(spot, k, sd):
    return 0.5 * (1 + math.erf(math.log(spot / k) / (sd * math.sqrt(2))))


def live(krows, kpath, now):
    collected = L5.utc(krows[0]["collected_utc"])
    ms = []
    for m in krows:
        if m.get("type") != "market" or m.get("series") != "KXBTCD" or m.get("strike_type") != "greater":
            continue
        h = (L5.utc(m["close_time"]) - collected).total_seconds() / 3600
        if H_MIN <= h <= H_MAX:
            ms.append(m)
    day = collected.strftime("%Y-%m-%d")
    run = {"type": "run", "rule": "layer13d", "snap": krows[0]["collected_utc"], "decided_utc": now.isoformat(),
           "commit": os.environ.get("GITHUB_SHA", "local"), "contracts_in_window": len(ms)}
    rows = []
    fi = forecast_inputs(pd.Timestamp(now)) if ms else None
    if ms and fi is None:
        run["reason"] = "Coinbase hourly candles incomplete"
    if fi is not None:
        spot, sigma13, base, s, end = fi
        run.update(spot=spot, sigma13_1h=sigma13, base_var_1h=base, coinbase_hour=end.isoformat(),
                   seasonal=[round(float(x), 4) for x in s.values])
        for m in ms:
            k = float(m["floor_strike"])
            bid, ask, bsz, asz = L5.kalshi_quote(m)
            if abs(k / spot - 1) > NEAR or not (bid > 0 and ask is not None and ask < 1 and ask > bid and ask - bid <= 0.10):
                continue
            close = pd.Timestamp(L5.utc(m["close_time"]))
            tau = (close - end).total_seconds() / 3600
            mid = (bid + ask) / 2
            p13_ln = p_above(spot, k, sigma13 * math.sqrt(tau))
            p13d_ln = p_above(spot, k, math.sqrt(seasonal_var(base, s, end, close)))
            blend = lambda pl: 1 / (1 + math.exp(-(B * lg(mid) + C * lg(pl))))
            rows.append({"type": "forecast", "ticker": m["ticker"], "event": m["event_ticker"], "strike": k,
                         "close_utc": close.isoformat(), "tau_h": round(tau, 3), "bid": bid, "ask": ask, "mid": mid,
                         "p13_lognormal": p13_ln, "p13": blend(p13_ln), "p13d_lognormal": p13d_ln, "p13d": blend(p13d_ln)})
    run["forecasts"] = len(rows)
    d = os.path.join(RAW, "paper_l13d", day)
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, f"paper_l13d_{os.path.basename(kpath).split('_')[-1]}")
    with gzip.open(out, "wt") as f:
        for r in [run] + rows:
            f.write(json.dumps(r) + "\n")
    print(f"paper l13d: {run.get('reason') or ''}{len(rows)} shadow forecasts logged -> {os.path.relpath(out, ROOT)}")
