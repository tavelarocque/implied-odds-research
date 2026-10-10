"""Diagnostic (Gatheral & Jacquier 2014): how often do the live SVI fits violate the exact no-butterfly condition?

The fitter penalizes Durrleman's g(k) < 0 softly, so small violations can survive. For every local snapshot
(data/raw/spx_options, ndx_options: same-day expiry fitted exactly as layer 5 does; data/raw/deribit_btc: the next
expiry, as the Bitcoin layer does), report min g over +/- 8 standard deviations and inside the quoted range, and
whether layer 5's own checks (mass within 5% of 1, negative mass < 1%) caught it. Changes nothing: diagnostic only.
"""
import glob, gzip, json, os, sys
from datetime import datetime, timezone
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from implied import surface_from_snapshot
from implied.crypto import deribit_surface

YEAR = 365 * 86400


def rows_of(p):
    return [json.loads(l) for l in gzip.open(p, "rt")]


def main():
    out = []
    for kind, root in (("spx_options", "SPXW"), ("ndx_options", "NDXP")):
        for p in sorted(glob.glob(os.path.join(ROOT, "data", "raw", kind, "*", f"{kind}_*Z.jsonl.gz"))):
            rows = rows_of(p)
            head, opts = rows[0], [r for r in rows[1:] if r.get("type") == "option"]
            t = pd.Timestamp(head["collected_utc"])
            day = t.strftime("%Y-%m-%d")
            secs = (pd.Timestamp(f"{day}T20:00:00Z") - t).total_seconds()
            if secs < 300:
                continue
            try:
                s = surface_from_snapshot(opts, day, secs / YEAR, spot_guess=float(head.get("spot") or 0) or None, root=root)
            except Exception:
                continue
            c, a = s.checks(), s.arb_check()
            out.append({"source": kind, "file": os.path.basename(p), **a,
                        "passes_layer5_checks": abs(c["mass"] - 1) <= 0.05 and c["negative_mass"] < 0.01})
    for p in sorted(glob.glob(os.path.join(ROOT, "data", "raw", "deribit_btc", "*", "deribit_btc_*Z.jsonl.gz"))):
        rows = rows_of(p)
        now = pd.Timestamp(rows[0]["collected_utc"]).to_pydatetime()
        opts = [r for r in rows[1:] if r.get("type") == "option"]
        exps = sorted({o["expiry"] for o in opts if pd.Timestamp(o["expiry"]) > pd.Timestamp(now)})
        if not exps:
            continue
        try:
            s = deribit_surface(opts, pd.Timestamp(exps[0]).to_pydatetime(), now)
        except Exception:
            continue
        c, a = s.checks(), s.arb_check()
        out.append({"source": "deribit_btc", "file": os.path.basename(p), **a,
                    "passes_layer5_checks": abs(c["mass"] - 1) <= 0.05 and c["negative_mass"] < 0.01})
    d = pd.DataFrame(out)
    for src, g in d.groupby("source"):
        print(f"{src}: {len(g)} fits; g < 0 somewhere within 8 sd: {(g.min_g < 0).mean():.0%} "
              f"(median share of grid {g.share_g_negative.median():.1%}); g < 0 inside the quoted range: "
              f"{(g.min_g_quoted < 0).mean():.0%}; Lee slope > 2: {(g.lee_slope > 2).mean():.0%}; "
              f"fits with g < 0 inside the quoted range that still pass layer 5's checks: "
              f"{int(((g.min_g_quoted < 0) & g.passes_layer5_checks).sum())}")
    d.to_csv(os.path.join(ROOT, "research", "output", "svi_arb_check.csv"), index=False)


if __name__ == "__main__":
    main()
