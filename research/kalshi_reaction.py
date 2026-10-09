"""Layer 7 (pre-registered in research/PREREGISTRATION_LAYER7.md): how fast does Kalshi's same-day ladder price an
index move?

Run from the project root:
    SMOKE=1 python3 research/kalshi_reaction.py     data quality only: index minutes per day, candle files on disk
    python3 research/kalshi_reaction.py             full analysis; refuses to run before 2026-11-30
    add --hourly for layer 7b (research/PREREGISTRATION_LAYER7B.md): the hourly above/below contracts
Before the full run, download the window's candles (from collect/):
    python3 kalshi_history.py markets --series KXINX KXNASDAQ100
    python3 kalshi_history.py candles --series KXINX KXNASDAQ100 --period 1 --since 2026-10-05
    python3 kalshi_history.py markets --series KXINXU KXNASDAQ100U --since 2026-10-05
    python3 kalshi_history.py candles --series KXINXU KXNASDAQ100U --period 1 --since 2026-10-05 --hours-before 1.2 --near 1
Output: research/output/kalshi_reaction/ (hourly: research/output/kalshi_reaction_hourly/)
"""
import gzip, io, json, os, subprocess, sys
from datetime import datetime, date
import numpy as np
import pandas as pd
from scipy.interpolate import PchipInterpolator

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from implied.kalshi_ladder import make_ladder, ladder_mids

START, END, RUN_AFTER = "2026-10-05", "2026-11-27", date(2026, 11, 30)
SERIES = {"KXINX": ("^GSPC", "S&P 500"), "KXNASDAQ100": ("^NDX", "Nasdaq-100")}
LAGS = list(range(-5, 11))
FIRST, LAST, N_BOOT = 360, 10, 2000
SMOKE = os.environ.get("SMOKE") == "1"
HOURLY = "--hourly" in sys.argv
# Layer 7b: each hourly above/below event, from 60 to 5 minutes before its close, strikes within 1% of the settled value.
SERIES_H = {"KXINXU": ("^GSPC", "S&P 500"), "KXNASDAQ100U": ("^NDX", "Nasdaq-100")}
H_FIRST, H_LAST, NEAR = 60, 5, 0.01
KH = os.path.join(ROOT, "data", "history", "kalshi")
OUT = os.path.join(ROOT, "research", "output", "kalshi_reaction" + ("_hourly" if HOURLY else ""))
rng = np.random.default_rng(7)


def index_minutes():
    """One-minute closes from every intraday file on the data branch, de-duplicated, indexed by bar END (UTC)."""
    subprocess.run(["git", "fetch", "-q", "origin", "data"], cwd=ROOT, check=True)
    names = subprocess.run(["git", "ls-tree", "-r", "--name-only", "origin/data"], cwd=ROOT,
                           capture_output=True, text=True, check=True).stdout.split()
    frames = []
    for n in sorted(x for x in names if x.startswith("data/raw/intraday/")):
        b = subprocess.run(["git", "show", f"origin/data:{n}"], cwd=ROOT, capture_output=True, check=True).stdout
        df = pd.read_csv(io.BytesIO(b), compression="gzip", header=[0, 1], index_col=0)
        df = df[[c for c in df.columns if c[0] == "Close"]]
        df.columns = [c[1] for c in df.columns]
        df.index = pd.to_datetime(df.index, utc=True, errors="coerce")
        frames.append(df[df.index.notna()])
    px = pd.concat(frames)
    px.index = pd.DatetimeIndex(pd.to_datetime(px.index, utc=True))   # files can differ in time resolution
    px = px[~px.index.duplicated(keep="last")].sort_index()
    px.index = px.index + pd.Timedelta(minutes=1)            # a bar stamped t covers t to t+1
    return px


def load_markets(series):
    """The window's markets only, filtered while reading: the hourly series files hold close to a million rows."""
    keep = ("strike_type", "floor_strike", "cap_strike", "close_time", "event_ticker", "ticker", "expiration_value",
            "result", "yes_sub_title", "subtitle", "title")
    rows = []
    for l in gzip.open(os.path.join(KH, f"markets_{series}.jsonl.gz"), "rt"):
        m = json.loads(l)
        if START <= (m.get("close_time") or "")[:10] <= END:
            rows.append(m if not HOURLY else {k: m.get(k) for k in keep})
    df = pd.DataFrame(rows, columns=None if rows else ["close_time", "ticker", "event_ticker", "strike_type"])
    df["day"] = df.close_time.str[:10]
    return df


def ladder_median(lad):
    """Level with 50% of the bids-only ladder above it (same construction as implied.kalshi_ladder.prob_above)."""
    p = ladder_mids(lad, "bid").values
    if not np.all(np.isfinite(p)):
        return np.nan
    hi = lad.hi.values
    edges, cdf, cum = [], [], 0.0
    for i in range(len(p)):
        cum += p[i]
        if np.isfinite(hi[i]):
            edges.append(hi[i]); cdf.append(cum)
    edges, cdf = np.array(edges), np.array(cdf)
    keep = np.r_[True, np.diff(edges) > 0]
    edges, cdf = edges[keep], np.maximum.accumulate(cdf[keep])
    if len(edges) < 2 or not (cdf[0] < 0.5 < cdf[-1]):
        return np.nan                                        # median inside a tail: undefined
    F = PchipInterpolator(edges, cdf)
    grid = np.linspace(edges[0], edges[-1], 4001)
    return float(np.interp(0.5, F(grid), grid))


def bid_px(c, k):
    """Yes bid in dollars. Candles name the field `close` (archived, dollars string; oldest, integer cents) or
    `close_dollars` (current API); the same three formats as research/calibration.py's dollars()."""
    b = c.get("yes_bid") or {}
    v = b.get(f"{k}_dollars")
    if v in (None, ""):
        v = b.get(k)
        if v in (None, ""):
            return np.nan
        if not isinstance(v, str):
            return float(v) / 100
    return float(v)


assert bid_px({"yes_bid": {"close_dollars": "0.12"}}, "close") == 0.12
assert bid_px({"yes_bid": {"close": "0.1200"}}, "close") == 0.12 and bid_px({"yes_bid": {"close": 12}}, "close") == 0.12


def bid_series(series, ticker, grid):
    """A contract's yes bid at each grid minute: close of its last candle at or before it (None if no candles)."""
    p = os.path.join(KH, "candles_1m", series, f"{ticker}.json.gz")
    if not os.path.exists(p):
        return None
    cs = json.load(gzip.open(p, "rt")).get("candlesticks", [])
    if not cs:
        return None
    ts = pd.to_datetime([c["end_period_ts"] for c in cs], unit="s", utc=True)
    # A candle with no bid field means no update that minute, not a zero bid: carry the last bid forward.
    s = pd.Series([bid_px(c, "close") for c in cs], index=ts).sort_index()
    s = s[~s.index.duplicated(keep="last")].ffill()
    first_open = next((v for v in (bid_px(c, "open") for c in cs) if np.isfinite(v)), 0.0)
    return s.reindex(grid, method="ffill").fillna(first_open)


def above_median(strikes, probs):
    """Level where P(index >= K), read from the above contracts' bids, crosses 50%. Bids are made non-increasing in
    the strike (running minimum), then interpolated linearly between the two strikes around 50%."""
    k, p = np.asarray(strikes, float), np.asarray(probs, float)
    o = np.argsort(k)
    k, p = k[o], p[o]
    keep = np.isfinite(p)
    k, p = k[keep], np.minimum.accumulate(p[keep])
    if len(k) < 3 or not (p[0] > 0.5 > p[-1]):
        return np.nan                                        # 50% outside the downloaded strikes: undefined
    i = int(np.argmax(p < 0.5))
    return float(k[i - 1] + (p[i - 1] - 0.5) / (p[i - 1] - p[i]) * (k[i] - k[i - 1]))


assert above_median([10, 20, 30], [0.9, 0.6, 0.2]) == 22.5 and np.isnan(above_median([10, 20, 30], [0.4, 0.3, 0.2]))


def hourly_medians(series, day_markets):
    """For each hourly event (keyed by its close), the implied median of its above contracts per minute, 60 to 5
    minutes before the close."""
    out = {}
    for ev, ms in day_markets.groupby("event_ticker"):
        ms = ms[ms.strike_type == "greater_or_equal"].copy()
        close = pd.Timestamp(ms.close_time.iloc[0]) if len(ms) else None
        if close is None or close.minute != 0:
            continue
        v = pd.to_numeric(ms.expiration_value, errors="coerce")
        ms = ms[(pd.to_numeric(ms.floor_strike) - v).abs() <= NEAR * v]
        grid = pd.date_range(close - pd.Timedelta(minutes=H_FIRST), close - pd.Timedelta(minutes=H_LAST), freq="1min")
        bids = {t: b for t in ms.ticker if (b := bid_series(series, t, grid)) is not None}
        if len(ms) < 3 or len(bids) < len(ms) * 0.8:
            continue
        k = dict(zip(ms.ticker, pd.to_numeric(ms.floor_strike)))
        out[close] = pd.Series({t: above_median([k[x] for x in bids], [bids[x][t] for x in bids]) for t in grid},
                               dtype=float)
    return out


def kalshi_medians(series, day_markets):
    """Per minute in the grid, the implied median of the day's range ladder."""
    out = {}
    for ev, ms in day_markets.groupby("event_ticker"):
        types = list(ms.strike_type)
        if not (types.count("less") == 1 and types.count("greater") == 1):
            continue
        close = pd.Timestamp(ms.close_time.iloc[0])
        grid = pd.date_range(close - pd.Timedelta(minutes=FIRST), close - pd.Timedelta(minutes=LAST), freq="1min")
        bids = {t: b for t in ms.ticker if (b := bid_series(series, t, grid)) is not None}
        if len(bids) < len(ms) * 0.8:
            continue
        lad0 = make_ladder(ms.assign(bid=0.0, ask=np.nan).to_dict("records"))
        for t in grid:
            lad = lad0.copy()
            lad["bid"] = [bids.get(tk, pd.Series(dtype=float)).get(t, 0.0) for tk in lad.ticker]
            out[t] = ladder_median(lad)
    return {pd.Timestamp(day_markets.close_time.iloc[0]): pd.Series(out, dtype=float)} if out else {}


def design(day_frame):
    """Rows for one contiguous block (a day, or one hourly event): dM_t and lagged dS. The block is put on a strict
    one-minute clock first, so a missing minute leaves a gap instead of turning a 2-minute change into a 1-minute one."""
    d = day_frame.sort_index().asfreq("1min")
    d["dM"], d["dS"] = d.M.diff(), d.S.diff()
    X = pd.DataFrame({f"L{j}": d.dS.shift(j) for j in LAGS})
    X["dM"] = d.dM
    return X.dropna()


def fit(X):
    A = np.column_stack([np.ones(len(X))] + [X[f"L{j}"].values for j in LAGS])
    beta = np.linalg.lstsq(A, X.dM.values, rcond=None)[0][1:]
    b = dict(zip(LAGS, beta))
    B = sum(b[j] for j in range(0, 11))
    cum = np.cumsum([b[j] for j in range(0, 11)])
    t50 = next((L for L, c in enumerate(cum) if B != 0 and c / B >= 0.5), 10)
    t90 = next((L for L, c in enumerate(cum) if B != 0 and c / B >= 0.9), 10)
    return {"B": B, "same_minute": b[0] / B if B else np.nan, "t50": t50, "t90": t90,
            "lead": sum(b[j] for j in range(-5, 0)), "b": b}


def boot(days):
    keys = list(days)
    res = []
    for _ in range(N_BOOT):
        pick = rng.choice(len(keys), len(keys))
        res.append(fit(pd.concat([days[keys[i]] for i in pick])))
    return res


def ci(vals):
    return np.nanpercentile(vals, [2.5, 97.5])


def main():
    SER, med = (SERIES_H, hourly_medians) if HOURLY else (SERIES, kalshi_medians)
    os.makedirs(OUT, exist_ok=True)
    px = index_minutes()
    lines = [f"{'Hourly contracts (layer 7b). ' if HOURLY else ''}Window {START} to {END}. Data quality:"]
    for series, (sym, name) in SER.items():
        s = px[sym].dropna() if sym in px else pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC"))
        s = s[(s.index >= pd.Timestamp(START, tz="UTC")) & (s.index <= pd.Timestamp(END, tz="UTC") + pd.Timedelta(days=1))]
        per_day = s.groupby(s.index.date).size()
        cdir = os.path.join(KH, "candles_1m", series)
        have = 0
        if os.path.exists(os.path.join(KH, f"markets_{series}.jsonl.gz")):
            mk = load_markets(series)
            have = sum(os.path.exists(os.path.join(cdir, f"{t}.json.gz")) for t in mk.ticker)
        lines.append(f"  {name:<10} index minutes {len(s)} on {len(per_day)} days (min {per_day.min() if len(per_day) else 0}/day); "
                     f"window candle files on disk: {have}")
    if SMOKE:
        print("\n".join(lines))
        return
    if date.today() < RUN_AFTER:
        sys.exit(f"Pre-registered to run on or after {RUN_AFTER}. Use SMOKE=1 for data quality only.")

    lines.append("")
    fits = {}
    for series, (sym, name) in SER.items():
        mk = load_markets(series)
        days, blocks = {}, {}
        for day, dm in mk.groupby("day"):
            parts = []
            for close, M in med(series, dm).items():
                M = M.dropna()
                if M.empty:
                    continue
                X = design(pd.DataFrame({"M": M, "S": px[sym].reindex(M.index)}))
                parts.append(X)
                blocks.setdefault(close.tz_convert("America/New_York").strftime("%H:%M") if HOURLY else None, []).append(X)
            X = pd.concat(parts) if parts else pd.DataFrame()
            if len(X) >= 60:
                days[day] = X
        if not days:
            lines.append(f"{name}: no usable days"); continue
        full, bs = fit(pd.concat(days.values())), boot(days)
        fits[series] = (days, bs)
        t90 = ci([r["t90"] for r in bs]); Bci = ci([r["B"] for r in bs]); lead = ci([r["lead"] for r in bs])
        speed = "fast" if t90[1] <= 2 else "slow" if t90[0] >= 5 else "moderate"
        comp = "underreacts" if Bci[1] < 1 else "overreacts" if Bci[0] > 1 else "complete"
        leadv = "Kalshi leads the index" if lead[0] > 0 or lead[1] < 0 else "no lead"
        lines.append(f"{name}: {len(days)} days, {sum(len(x) for x in days.values())} minutes")
        lines.append(f"  total response B {full['B']:.3f} ({Bci[0]:.3f} to {Bci[1]:.3f}) -> {comp}")
        lines.append(f"  same-minute share {full['same_minute']:.2f}; 50% time {full['t50']} min; 90% time {full['t90']} min "
                     f"({t90[0]:.0f} to {t90[1]:.0f}) -> {speed}")
        lines.append(f"  lead sum {full['lead']:+.3f} ({lead[0]:+.3f} to {lead[1]:+.3f}) -> {leadv}")
        lines.append("  lag coefficients: " + ", ".join(f"{j}:{full['b'][j]:+.3f}" for j in LAGS))
        if HOURLY:
            groups = {k: v for k, v in sorted(blocks.items()) if sum(map(len, v)) >= 200}
            label = "by event close, ET (reported only): "
        else:
            groups = {}
            for day, X in days.items():
                n = len(X)
                for lbl, sl in (("6-4", slice(0, n // 3)), ("4-2", slice(n // 3, 2 * n // 3)), ("2-0", slice(2 * n // 3, n))):
                    groups.setdefault(lbl, []).append(X.iloc[sl])
            label = "by hours to close (reported only): "
        lines.append("  " + label + ", ".join(
            f"{k}: B {fit(pd.concat(v))['B']:.2f}, 90% {fit(pd.concat(v))['t90']} min" for k, v in groups.items()))
    if len(fits) == 2:
        (dA, _), (dB, _) = (fits[k] for k in SER)
        common = sorted(set(dA) & set(dB))
        diffs = []
        for _ in range(N_BOOT):
            pick = rng.choice(common, len(common))
            diffs.append(fit(pd.concat([dA[d] for d in pick]))["t90"] - fit(pd.concat([dB[d] for d in pick]))["t90"])
        lo, hi = ci(diffs)
        lines.append(f"\nS&P minus Nasdaq 90% time, paired by day (reported only): {lo:+.0f} to {hi:+.0f} min")
    txt = "\n".join(lines)
    print(txt)
    open(os.path.join(OUT, "summary.txt"), "w").write(txt + "\n")


if __name__ == "__main__":
    main()
