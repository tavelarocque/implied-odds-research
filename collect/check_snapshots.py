"""Sanity checks on the latest live snapshot of every kind: options (S&P and Nasdaq), Kalshi ladders, Polymarket books.

Collectors can "succeed" while saving garbage (a field renamed, a unit changed, an empty book). This catches that
before weeks of bad data pile up. It also lines the three sources up against each other on the same moment.

Run from the project root:
  python3 collect/check_snapshots.py            latest files in data/raw/ (synced on Sundays)
  python3 collect/check_snapshots.py --cloud    latest files on the cloud `data` branch (fetches first)
"""
import glob, gzip, json, math, os, subprocess, sys, tempfile
from collections import defaultdict
from datetime import datetime

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from implied import surface_from_snapshot  # noqa: E402
from implied.kalshi_ladder import make_ladder  # noqa: E402

KINDS = ["spx_options", "ndx_options", "kalshi", "polymarket"]
PM_ROOT = {"spx_options": "SPXW", "ndx_options": "NDXP"}
KALSHI_INDEX = {"KXINX": "spx_options", "KXNASDAQ100": "ndx_options"}
POLY_INDEX = {"close": "spx_options", "ndx_close": "ndx_options"}

fails, warns = [], []


def check(ok, msg, warn_only=False):
    print(f"  {'ok  ' if ok else ('WARN' if warn_only else 'FAIL')}  {msg}")
    if not ok:
        (warns if warn_only else fails).append(msg)


def num(x):
    try:
        v = float(str(x).replace(",", ""))
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def read(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(l) for l in f]


def latest_paths(cloud):
    if not cloud:
        out = {}
        for k in KINDS:
            files = sorted(glob.glob(os.path.join(ROOT, "data", "raw", k, "*", "*.gz")))
            if files:
                out[k] = files[-1]
        return out
    subprocess.run(["git", "fetch", "-q", "origin", "data"], cwd=ROOT, check=True)
    names = subprocess.run(["git", "ls-tree", "-r", "--name-only", "origin/data"], cwd=ROOT,
                           capture_output=True, text=True, check=True).stdout.split()
    tmp, out = tempfile.mkdtemp(), {}
    for k in KINDS:
        files = sorted(n for n in names if n.startswith(f"data/raw/{k}/"))
        if files:
            dest = os.path.join(tmp, os.path.basename(files[-1]))
            with open(dest, "wb") as fh:
                fh.write(subprocess.run(["git", "show", f"origin/data:{files[-1]}"], cwd=ROOT,
                                        capture_output=True, check=True).stdout)
            out[k] = dest
    return out


def years_between(a_iso, b_iso):
    a = datetime.fromisoformat(a_iso.replace("Z", "+00:00"))
    b = datetime.fromisoformat(b_iso.replace("Z", "+00:00"))
    return max((b - a).total_seconds(), 3600) / (365 * 86400)


# ---------------------------------------------------------------- options
def check_options(kind, rows, surfaces):
    head, opts = rows[0], [r for r in rows[1:] if r.get("type") == "option"]
    spot, root = num(head.get("spot")), PM_ROOT[kind]
    print(f"\n{kind}: {len(opts)} options, spot {spot}, feed time {head.get('feed_timestamp')}")
    check(spot is not None and spot > 0, "spot price present")
    check(len(opts) > 500, f"enough option rows ({len(opts)})")
    pm = [o for o in opts if o.get("root") == root]
    check(len(pm) > 100, f"PM-settled {root} rows present ({len(pm)})")
    quoted = [o for o in opts if (num(o.get("bid")) or 0) > 0 and num(o.get("ask")) is not None]
    crossed = [o for o in quoted if num(o["bid"]) > num(o["ask"])]
    check(len(crossed) <= 0.01 * max(len(quoted), 1), f"crossed quotes (bid > ask): {len(crossed)} of {len(quoted)}")
    expiries = sorted({o["expiry"] for o in pm})
    check(bool(expiries), f"{root} expiries: {', '.join(expiries[:6])}")

    # Static no-arbitrage on the nearest expiry: call mids must fall as the strike rises.
    if expiries:
        e = expiries[0]
        calls = sorted((num(o["strike"]), (num(o["bid"]) + num(o["ask"])) / 2) for o in pm
                       if o["expiry"] == e and o["cp"] == "C" and (num(o.get("bid")) or 0) > 0 and num(o.get("ask")))
        rises = sum(1 for (k1, c1), (k2, c2) in zip(calls, calls[1:]) if c2 > c1 + 0.5)
        check(rises <= 0.02 * max(len(calls), 1), f"{e} call mids non-increasing in strike ({rises} violations of {len(calls)})",
              warn_only=True)

    # Fit the smile on each expiry within a week and check the density integrates sensibly.
    for e in expiries[:4]:
        T = years_between(head["collected_utc"], f"{e}T20:00:00Z")
        try:
            s = surface_from_snapshot(opts, e, T, spot_guess=spot, root=root)
        except Exception as ex:
            check(False, f"{e}: smile fit failed ({ex})", warn_only=True)
            continue
        c = s.checks()
        surfaces[(kind, e)] = s
        good = abs(c["mass"] - 1) < 0.03 and c["negative_mass"] < 0.01 and abs(s.F / spot - 1) < 0.02
        check(good, f"{e}: forward {s.F:,.1f} ({100 * (s.F / spot - 1):+.2f}% vs spot), ATM vol "
                    f"{float(s.sigma(s.F)):.1%}, density mass {c['mass']:.3f}, negative mass {c['negative_mass']:.4f}")


# ---------------------------------------------------------------- kalshi
def kalshi_quote(m):
    bid = num(m.get("yes_bid_dollars")) or 0.0
    ask = num(m.get("yes_ask_dollars"))
    if ask is not None and (ask >= 1.0 or (num(m.get("yes_ask_size_fp")) or 0) == 0):
        ask = None                                      # 1.00 with no size = nobody selling
    return bid, ask


def check_kalshi(rows, surfaces, collected):
    markets = [m for m in rows if m.get("type") == "market"]
    by_series = defaultdict(lambda: defaultdict(list))
    for m in markets:
        by_series[m["series"]][m["event_ticker"]].append(m)
    print(f"\nkalshi: {len(markets)} markets, series {', '.join(f'{s} ({sum(len(v) for v in e.values())})' for s, e in by_series.items())}")
    check(len(markets) > 0, "markets present")
    for series in ("KXINX", "KXNASDAQ100"):
        check(series in by_series, f"{series} present")

    for series, events in by_series.items():
        for ev, ms in sorted(events.items()):
            types = [m.get("strike_type") for m in ms]
            if not (types.count("less") == 1 and types.count("greater") == 1 and "between" in types):
                continue                                # not a full range ladder (e.g. an above/below event)
            lad = make_ladder([{**m, "bid": kalshi_quote(m)[0], "ask": kalshi_quote(m)[1]} for m in ms])
            gaps = np.abs(lad.lo.values[1:] - lad.hi.values[:-1])
            contiguous = bool(np.all(gaps < 1.0))
            sb, sa = lad.bid.sum(), lad.ask.sum(min_count=len(lad))
            check(contiguous, f"{ev}: {len(lad)} ranges contiguous, no gaps or overlaps")
            check(sb <= 1.0 + 1e-9, f"{ev}: sum of bids {sb:.2f} <= 1 (else selling every range is free money)")
            if not np.isnan(sa):
                check(sa >= 1.0 - 1e-9, f"{ev}: sum of asks {sa:.2f} >= 1 (else buying every range is free money)")
            # Cross-source: option-implied probability of each quoted range vs Kalshi's bid-ask.
            idx = KALSHI_INDEX.get(series)
            expiry = ms[0]["close_time"][:10]
            s = surfaces.get((idx, expiry))
            if s is None or sb == 0:
                continue
            inside, n, gap = 0, 0, []
            for _, r in lad.iterrows():
                if r.ask is None or np.isnan(r.ask) or r.ask - r.bid > 0.10:
                    continue
                p = s.prob_between(None if np.isinf(r.lo) else r.lo, None if np.isinf(r.hi) else r.hi)
                n += 1
                inside += r.bid <= p <= r.ask
                gap.append(abs(p - (r.bid + r.ask) / 2))
            if n:
                print(f"        vs options ({expiry}): option probability inside Kalshi bid-ask on {inside} of {n} "
                      f"tightly quoted ranges; mean gap to mid {100 * np.mean(gap):.1f}pp")


# ---------------------------------------------------------------- polymarket
def check_polymarket(rows, surfaces, opt_heads):
    markets = [m for m in rows if m.get("type") == "market"]
    print(f"\npolymarket: {len(markets)} markets")
    check(len(markets) > 0, "markets present (none is normal only if no daily market is listed yet)", warn_only=True)
    for m in markets:
        books = m.get("books") or {}
        print(f"  {m['slug']}  ({m.get('kind')}, volume {num(m.get('volume')) or 0:,.0f})")
        bb = {}
        for side, b in books.items():
            bids, asks = b.get("bids") or [], b.get("asks") or []
            bid, ask = b.get("best_bid"), b.get("best_ask")
            bb[side] = (bid, ask)
            ordered = all(x[0] >= y[0] for x, y in zip(bids, bids[1:])) and all(x[0] <= y[0] for x, y in zip(asks, asks[1:]))
            check(ordered, f"{side}: book levels sorted (bids high to low, asks low to high)")
            if bid is not None and ask is not None:
                check(bid < ask, f"{side}: bid {bid:.3f} < ask {ask:.3f} (spread {100 * (ask - bid):.1f}c)")
        if {"Up", "Down"} <= bb.keys() and None not in bb["Up"] + bb["Down"]:
            (ub, ua), (db, da) = bb["Up"], bb["Down"]
            check(ub + db <= 1.0 + 1e-9, f"Up bid + Down bid = {ub + db:.3f} <= 1")
            check(ua + da >= 1.0 - 1e-9, f"Up ask + Down ask = {ua + da:.3f} >= 1")
            # Cross-source: options-implied P(close above the previous close) vs Polymarket's Up price.
            idx = POLY_INDEX.get(m.get("kind"))
            s = surfaces.get((idx, m.get("date")))
            prev = num((opt_heads.get(idx) or {}).get("prev_close"))
            if s is not None and prev:
                p = s.prob_above(prev)
                print(f"        vs options: P(close > previous close {prev:,.2f}) = {p:.3f}; "
                      f"Polymarket Up {ub:.2f}/{ua:.2f} {'(inside)' if ub <= p <= ua else '(outside)'}")


def main():
    cloud = "--cloud" in sys.argv
    paths = latest_paths(cloud)
    print(f"Checking the latest {'cloud' if cloud else 'local'} snapshots:")
    for k in KINDS:
        print(f"  {k:12} {os.path.basename(paths[k]) if k in paths else 'MISSING'}")
        check(k in paths, f"{k} snapshot exists")
    data = {k: read(p) for k, p in paths.items()}
    surfaces = {}
    for k in ("spx_options", "ndx_options"):
        if k in data:
            check_options(k, data[k], surfaces)
    if "kalshi" in data:
        check_kalshi(data["kalshi"], surfaces, data["kalshi"][0].get("collected_utc"))
    if "polymarket" in data:
        check_polymarket(data["polymarket"], surfaces, {k: data[k][0] for k in ("spx_options", "ndx_options") if k in data})
    print(f"\n{len(fails)} failed, {len(warns)} warnings")
    for f in fails:
        print(f"  FAIL  {f}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
