"""Layer 5s (research/PREREGISTRATION_LAYER5S.md): split layer 5's Bitcoin trades into "move" and "stay" bets.

    python research/layer5s.py            running tally inside the registered window (nothing decided before the readout)
    python research/layer5s.py --check    same code on the pre-registration data (2026-10-09 to the start), for testing
"""
import os, subprocess, sys
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "trade")); sys.path.insert(0, os.path.join(ROOT, "research"))
START, END, END_EXT = pd.Timestamp("2026-10-15T06:00Z"), pd.Timestamp("2026-11-08T00:00Z"), pd.Timestamp("2026-11-28T00:00Z")
READOUT, MIN_STAY, MIN_DAYS, N_BOOT, SEED = pd.Timestamp("2026-11-09", tz="UTC"), 300, 15, 2000, 515


def label(t):
    """move = a bet that Bitcoin ends farther from spot than Kalshi priced; stay = the opposite."""
    return "move" if (t["side"] == "buy") == (t["strike"] > t["spot"]) else "stay"


def frame():
    import paper as P
    trades, res = P.all_trades("paper_btc", "paper_btc_results")
    rows = []
    for d, ts in trades.items():
        for t in ts:
            r = res.get(d, {}).get(t["ticker"])
            if r in ("yes", "no"):
                snap = pd.Timestamp(t["snap"])
                rows.append(dict(snap=snap, day=snap.strftime("%Y-%m-%d"), label=label(t), kind=t.get("kind"),
                                 dist=abs(t["strike"] / t["spot"] - 1), pnl=P.pnl_of(t, r), ticker=t["ticker"]))
    return pd.DataFrame(rows)


def boot(df, stat, rng):
    days = df.day.unique()
    g = {d: x for d, x in df.groupby("day")}
    out = [stat(pd.concat([g[d] for d in rng.choice(days, len(days))])) for _ in range(N_BOOT)]
    return np.nanpercentile(out, [2.5, 97.5])


def mean_of(lab):
    return lambda x: x.loc[x.label == lab, "pnl"].mean()


def analyse(df, title):
    rng = np.random.default_rng(SEED)
    print(f"{title}: {len(df)} settled trades over {df.day.nunique()} days")
    if df.empty:
        return None
    for lab in ("stay", "move"):
        g = df[df.label == lab]
        print(f"  {lab:<5} {len(g):>4} trades, won {(g.pnl > 0).mean():.0%}, total ${g.pnl.sum():,.2f}, "
              f"mean ${g.pnl.mean() if len(g) else float('nan'):.2f}")
    h1 = (mean_of("stay")(df), *boot(df, mean_of("stay"), rng))
    h2 = (mean_of("stay")(df) - mean_of("move")(df), *boot(df, lambda x: mean_of("stay")(x) - mean_of("move")(x), rng))
    h3 = (mean_of("move")(df), *boot(df, mean_of("move"), rng))
    for name, (e, lo, hi) in (("H1 stay mean > 0", h1), ("H2 stay - move > 0", h2), ("H3 move mean < 0", h3)):
        print(f"  {name:<20} {e:+8.2f}  95% [{lo:+.2f}, {hi:+.2f}]")
    for col, cut in (("kind", None), ("dist", 3)):
        x = df.assign(bucket=pd.qcut(df.dist, cut, labels=["near", "mid", "far"]) if cut else df[col])
        print("  " + x.groupby(["bucket", "label"], observed=True).pnl.agg(["count", "sum"]).round(2)
              .to_string().replace("\n", "\n  "))
    if h1[1] > 0 and h2[1] > 0:
        verdict = "stay-side edge confirmed"
    elif h1[1] > 0:
        verdict = "no split"
    else:
        verdict = "not confirmed"
    return verdict


def main():
    subprocess.run(["git", "fetch", "-q", "origin", "+refs/heads/data:refs/remotes/origin/data"], cwd=ROOT)
    df = frame()
    if "--check" in sys.argv:
        v = analyse(df[df.snap < START], "pre-registration data (NOT part of the test)")
        print(f"  (rule applied to these, for testing only: {v})")
        return
    now = pd.Timestamp.now(tz="UTC")
    win = df[(df.snap >= START) & (df.snap < END)]
    extended = win[win.label == "stay"].shape[0] < MIN_STAY or win.day.nunique() < MIN_DAYS
    if now >= READOUT and extended:
        win = df[(df.snap >= START) & (df.snap < END_EXT)]
    v = analyse(win, "layer 5s registered window" + (" (extended to 2026-11-28)" if extended and now >= READOUT else ""))
    if now < READOUT:
        print(f"  running tally only; the readout is {READOUT.date()} (or 2026-11-30 if extended). Nothing is decided yet.")
    elif extended and now < pd.Timestamp("2026-11-30", tz="UTC"):
        print("  too few trades by 2026-11-09; window extended, read with layer 5 on 2026-11-30.")
    else:
        print(f"  VERDICT: {v}")


if __name__ == "__main__":
    main()
