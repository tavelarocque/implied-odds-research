"""Export Bitcoin snapshots for the OCaml contracts project.

For every Kalshi KXBTCD snapshot paired with a Deribit snapshot (the same pairing and fit checks as layer 5), writes
  surfaces.csv   one row per (snapshot, Kalshi event): the Deribit SVI smile moved to that event's settlement time
  contracts.csv  one row per Kalshi contract: strike, bid/ask/sizes, and p_opt = P(BTC > strike) from that smile,
                 computed by implied/bl.py (the reference value an independent pricer should reproduce)
  README.txt     column definitions and the exact formulas
into data/export/ocaml/ (git-ignored). Reads the data branch, so run `git fetch origin data` first (the digest does).

    .venv/bin/python tools/export_for_ocaml.py               last 3 UTC days
    .venv/bin/python tools/export_for_ocaml.py --days 7
    .venv/bin/python tools/export_for_ocaml.py --date 2026-10-15
"""
import argparse, csv, math, os, subprocess, sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "research")]
import options_vs_kalshi as L5
from implied.crypto import deribit_surface, at_time, YEAR

SERIES, KK, DK = "KXBTCD", "kalshi_crypto", "deribit_btc"
OUT = os.path.join(ROOT, "data", "export", "ocaml")
F17 = lambda x: "" if x is None else format(float(x), ".17g")      # full precision, so values round-trip exactly

README = """Implied Odds -> OCaml export (Bitcoin, Kalshi KXBTCD vs Deribit options)

surfaces.csv: one row per (snapshot, Kalshi event)
  snap_utc        when the Kalshi snapshot was taken (ISO 8601, UTC)
  event           Kalshi event ticker (one settlement time, many strikes)
  close_utc       the event's settlement time (ISO 8601, UTC)
  kind            hourly | daily
  hours_to_close  (close_utc - snap_utc) in hours
  spot            Deribit BTC index at the snapshot (USD)
  F               forward to the settlement time (USD)
  T               time to settlement in years (365-day year)
  a b rho m s     raw SVI parameters of total implied variance at settlement (see below)
  k_min k_max     log-moneyness range covered by quoted Deribit options; outside it the smile is extrapolated

contracts.csv: one row per Kalshi contract in that event ("BTC above strike at close_utc")
  snap_utc event ticker strike
  bid ask         Kalshi YES bid and ask in dollars (0..1); ask is empty when there is no usable ask
  bid_size ask_size  contracts shown at the touch
  in_range        1 if ln(strike/F) is inside [k_min, k_max]
  p_opt           P(BTC > strike at close_utc) from the smile, computed in Python (implied/bl.py). Reference value.

Formulas (exactly what produced p_opt; discount factor DF = 1, Deribit uses a zero rate):
  k(K)      = ln(K / F)
  w(k)      = a + b * (rho * (k - m) + sqrt((k - m)^2 + s^2))        total implied variance
  sigma(K)  = sqrt(max(w(k), 1e-10) / T)                               Black implied volatility
  d1        = (ln(F / K) + sigma^2 T / 2) / (sigma sqrt(T)),  d2 = d1 - sigma sqrt(T)
  C(K)      = DF * (F * N(d1) - K * N(d2))                             N = standard normal CDF = (1 + erf(x/sqrt 2)) / 2
  p_opt(K)  = -(C(K + h) - C(K - h)) / (2 h) / DF,   h = F * 1e-4      P(S_T > K), central difference
These are risk-neutral probabilities: they carry the volatility risk premium and are not real-world forecasts.
Numbers are written with 17 significant digits, so a correct reimplementation should match p_opt to about 1e-9.
Kalshi settles a contract YES if the BTC reference price at close_utc is above the strike.
"""


def names(day, kind):
    out = subprocess.run(["git", "ls-tree", "-r", "--name-only", "origin/data", f"data/raw/{kind}/{day}/"],
                         cwd=ROOT, capture_output=True, text=True).stdout.split()
    return sorted(out, key=L5.stamp_seconds)


def export_day(day, sw, cw, counts):
    ks, ds = names(day, KK), names(day, DK)
    for kn in ks:
        t = L5.stamp_seconds(kn)
        near = min(ds, key=lambda n: abs(L5.stamp_seconds(n) - t), default=None)
        if near is None or abs(L5.stamp_seconds(near) - t) > L5.MAX_PAIR_S:
            continue
        krows, drows = L5.load(kn), L5.load(near)
        collected = L5.utc(krows[0]["collected_utc"])
        spot = float(drows[0]["index_price"])
        opts = [r for r in drows[1:] if r.get("type") == "option"]
        markets = [m for m in krows if m.get("type") == "market" and m.get("series") == SERIES
                   and m.get("strike_type") == "greater"]
        fits = {}
        for ev in sorted({m["event_ticker"] for m in markets}):
            em = [m for m in markets if m["event_ticker"] == ev]
            close = L5.utc(em[0]["close_time"])
            secs = (close - collected).total_seconds()
            if secs < L5.MIN_TO_CLOSE_S:
                continue
            kind = "daily" if L5.utc(em[0]["open_time"]) <= close - timedelta(hours=2) else "hourly"
            try:
                exp = L5.utc(sorted({o["expiry"] for o in opts if L5.utc(o["expiry"]) >= close})[0])
                if exp not in fits:
                    fits[exp] = deribit_surface(opts, exp, collected)
                surf = at_time(fits[exp], secs / YEAR, spot)
                c = surf.checks()
                if abs(c["mass"] - 1) > 0.05 or c["negative_mass"] >= 0.01:
                    counts["bad_fit"] += 1; continue
            except Exception:
                counts["bad_fit"] += 1; continue
            a, b, rho, m, s = surf.params
            sw.writerow([krows[0]["collected_utc"], ev, close.isoformat(), kind, F17(secs / 3600), F17(spot),
                         F17(surf.F), F17(surf.T), F17(a), F17(b), F17(rho), F17(m), F17(s),
                         F17(surf.k_min), F17(surf.k_max)])
            counts["surfaces"] += 1
            for mk in em:
                bid, ask, bsz, asz = L5.kalshi_quote(mk)
                K = float(mk["floor_strike"])
                cw.writerow([krows[0]["collected_utc"], ev, mk["ticker"], F17(K), F17(bid), F17(ask), F17(bsz),
                             F17(asz), int(bool(surf.in_fitted_range(K))), F17(float(surf.prob_above(K)))])
                counts["contracts"] += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--date")
    args = ap.parse_args()
    subprocess.run(["git", "fetch", "-q", "origin", "+refs/heads/data:refs/remotes/origin/data"], cwd=ROOT)
    today = datetime.now(timezone.utc).date()
    days = [args.date] if args.date else [str(today - timedelta(days=i)) for i in range(args.days - 1, -1, -1)]
    os.makedirs(OUT, exist_ok=True)
    counts = {"surfaces": 0, "contracts": 0, "bad_fit": 0}
    with open(os.path.join(OUT, "surfaces.csv"), "w", newline="") as fs, \
         open(os.path.join(OUT, "contracts.csv"), "w", newline="") as fc:
        sw, cw = csv.writer(fs), csv.writer(fc)
        sw.writerow(["snap_utc", "event", "close_utc", "kind", "hours_to_close", "spot", "F", "T",
                     "a", "b", "rho", "m", "s", "k_min", "k_max"])
        cw.writerow(["snap_utc", "event", "ticker", "strike", "bid", "ask", "bid_size", "ask_size", "in_range", "p_opt"])
        for d in days:
            export_day(d, sw, cw, counts)
    open(os.path.join(OUT, "README.txt"), "w").write(README)
    print(f"export: {', '.join(days)} -> {os.path.relpath(OUT, ROOT)}: {counts['surfaces']} surfaces, "
          f"{counts['contracts']} contracts ({counts['bad_fit']} event fits failed checks and were skipped)")


if __name__ == "__main__":
    main()
