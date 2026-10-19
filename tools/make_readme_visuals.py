"""README visuals for Implied Odds (options-only: no Kalshi prices, nothing from the sealed comparisons).

1. assets/density_collapse_{light,dark}.png  BTC risk-neutral density for one Kalshi daily event, one curve per
   hourly snapshot, from ~2 days out to the last hour: the market's uncertainty collapsing toward settlement.
2. assets/vol_surface_{light,dark}.png        Deribit BTC implied-volatility surface (SVI per expiry).
3. assets/vol_surface.stl                     the same surface as an ASCII STL mesh (GitHub renders it in 3D).
"""
import gzip, json, math, sys
from datetime import datetime
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import cm
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401
from mpl_toolkits.mplot3d.art3d import PolyCollection
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))
from implied.bl import fit_surface, svi_total_variance, black_call

# Usage: python tools/make_readme_visuals.py data/export/ocaml/surfaces.csv data/raw/deribit_btc/<day>/<file>.jsonl.gz
# (run from the repo root; writes into assets/)
SURF, DERIBIT = sys.argv[1], sys.argv[2]
__import__('os').makedirs('assets', exist_ok=True)
THEMES = {
    "light": dict(bg="#ffffff", fg="#1f2328", muted="#656d76", grid="#d0d7de", cmap="viridis"),
    "dark":  dict(bg="#0d1117", fg="#e6edf3", muted="#8b949e", grid="#30363d", cmap="plasma"),
}

# ---------- 1. density collapse ----------
s = pd.read_csv(SURF)
ev = s[(s.event == "KXBTCD-26OCT1617") & (s.kind == "daily")].sort_values("hours_to_close", ascending=False)
# Every other hour, from 3 h out: closer than that the density is a near-spike that flattens every other ridge.
# Fits with s < 1e-4 are near-kink SVI smiles (known limitation, research/PREREGISTRATION_BTC.md) and are skipped.
ev = ev[(ev.hours_to_close >= 3) & (ev.s >= 1e-4)].iloc[::2]
#          # every other hour; the last 2 h are a near-spike that flattens the rest
K = np.linspace(77500, 85500, 900)


def density(row):
    k = np.log(K / row.F)
    sig = np.sqrt(np.maximum(svi_total_variance(k, row.a, row.b, row.rho, row.m, row.s), 1e-10) / row.T)
    C = black_call(row.F, K, row.T, sig, 1.0)
    return np.maximum(np.gradient(np.gradient(C, K), K), 0) * 1000   # per $1,000


dens = [density(r) for r in ev.itertuples()]
hours = ev.hours_to_close.values
close = pd.Timestamp(ev.close_utc.iloc[0]).tz_convert("America/New_York")

for name, t in THEMES.items():
    fig = plt.figure(figsize=(12, 6.2), facecolor=t["bg"])
    ax = fig.add_subplot(111, projection="3d", facecolor=t["bg"])
    cmap = matplotlib.colormaps[t["cmap"]]
    zmax = max(d.max() for d in dens)
    for i, (h, d) in enumerate(zip(hours, dens)):
        c = cmap(0.15 + 0.8 * i / (len(dens) - 1))
        verts = [list(zip(K / 1000, d))]
        verts[0] = [(K[0] / 1000, 0)] + verts[0] + [(K[-1] / 1000, 0)]
        poly = PolyCollection(verts, facecolors=[(*c[:3], 0.55)], edgecolors=[c], linewidths=1.0)
        ax.add_collection3d(poly, zs=h, zdir="y")
    ax.set_xlim(K[0] / 1000, K[-1] / 1000); ax.set_ylim(hours.max() + 1, 0); ax.set_zlim(0, zmax * 1.05)
    ax.set_xlabel("Bitcoin price at settlement ($ thousands)", color=t["fg"], labelpad=10)
    ax.set_ylabel("hours before settlement", color=t["fg"], labelpad=10)
    ax.set_zlabel("probability per $1,000", color=t["fg"], labelpad=8)
    for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
        axis.set_pane_color((0, 0, 0, 0)); axis._axinfo["grid"]["color"] = t["grid"]
        axis.line.set_color(t["grid"])
    ax.tick_params(colors=t["muted"], labelsize=8)
    ax.view_init(elev=24, azim=-58)
    ax.set_box_aspect((1.6, 1.25, 0.65))
    fig.text(0.06, 0.92, "Where the options market thinks Bitcoin will settle", color=t["fg"], fontsize=15,
             fontweight="bold")
    fig.text(0.06, 0.835, f"Risk-neutral density for Kalshi's {close:%b %-d} 5pm ET contract, re-estimated every "
             f"2 hours from Deribit options (SVI + Breeden–Litzenberger).\nFrom two days out to three hours out, the market's uncertainty collapses as settlement nears.",
             color=t["muted"], fontsize=9.5)
    fig.subplots_adjust(left=0, right=1, bottom=0, top=0.95)
    fig.savefig(f"assets/density_collapse_{name}.png", dpi=170, facecolor=t["bg"])
    plt.close(fig)

# ---------- 2. vol surface ----------
rows = [json.loads(l) for l in gzip.open(DERIBIT, "rt")]
hdr = rows[0]; now = pd.Timestamp(hdr["collected_utc"])
o = pd.DataFrame([r for r in rows if r["type"] == "option"])
slices = []
for exp, g in o.groupby("expiry"):
    T = (pd.Timestamp(exp) - now).total_seconds() / (365 * 86400)
    F = g.underlying_price.mean()
    piv = g.assign(mid=(g.bid + g.ask) / 2 * g.underlying_price).pivot_table(index="strike", columns="cp", values="mid")
    piv = piv[(piv.index > F * 0.85) & (piv.index < F * 1.15)]
    sf = fit_surface(piv.index.values, piv.get("C").values, piv.get("P").values, T, forward=(F, 1.0))
    slices.append((T, sf.params if hasattr(sf, "params") else None, sf))
print("expiries", [(round(T * 365, 2)) for T, _, _ in slices])


def svi_params(sf):
    for attr in ("params", "svi", "p"):
        if hasattr(sf, attr):
            return getattr(sf, attr)
    return sf.__dict__.get("params")


ks = np.linspace(-0.06, 0.06, 61)
Ts = np.array([T for T, _, _ in slices])
W = np.array([svi_total_variance(ks, *svi_params(sf)) for _, _, sf in slices])   # total variance, rows = expiries
Tg = np.linspace(Ts.min(), Ts.max(), 40)
Wg = np.array([[np.interp(t, Ts, W[:, j]) for j in range(len(ks))] for t in Tg])  # linear in total variance
IV = np.sqrt(np.maximum(Wg, 1e-12) / Tg[:, None]) * 100
KK, TT = np.meshgrid(ks * 100, Tg * 365)

for name, t in THEMES.items():
    fig = plt.figure(figsize=(12, 6.2), facecolor=t["bg"])
    ax = fig.add_subplot(111, projection="3d", facecolor=t["bg"])
    ax.plot_surface(KK, TT, IV, cmap=t["cmap"], linewidth=0.15, edgecolor=t["grid"], antialiased=True, alpha=0.95,
                    rstride=1, cstride=1)
    for T_, _, sf in slices:
        w = svi_total_variance(ks, *svi_params(sf))
        ax.plot(ks * 100, np.full_like(ks, T_ * 365), np.sqrt(w / T_) * 100 + 0.15, color=t["fg"], lw=1.6, zorder=10)
    ax.set_xlabel("log-moneyness ln(K/F), %", color=t["fg"], labelpad=10)
    ax.set_ylabel("days to expiry", color=t["fg"], labelpad=10)
    ax.set_zlabel("implied volatility, %", color=t["fg"], labelpad=8)
    for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
        axis.set_pane_color((0, 0, 0, 0)); axis._axinfo["grid"]["color"] = t["grid"]; axis.line.set_color(t["grid"])
    ax.tick_params(colors=t["muted"], labelsize=8)
    ax.view_init(elev=20, azim=-62)
    ax.set_box_aspect((1.5, 1.2, 0.7))
    fig.text(0.06, 0.92, "Bitcoin implied-volatility surface", color=t["fg"], fontsize=15, fontweight="bold")
    fig.text(0.06, 0.875, f"Deribit BTC options, {now:%Y-%m-%d %H:%M} UTC. One arbitrage-checked SVI smile per expiry "
             f"(lines), interpolated in total variance between them.", color=t["muted"], fontsize=9.5)
    fig.subplots_adjust(left=0, right=1, bottom=0, top=0.95)
    fig.savefig(f"assets/vol_surface_{name}.png", dpi=170, facecolor=t["bg"])
    plt.close(fig)

# ---------- 3. STL ----------
# Coarser grid so the ASCII file stays small; axes rescaled to similar magnitudes for a pleasant default view.
ks2 = np.linspace(-0.06, 0.06, 33); Tg2 = np.linspace(Ts.min(), Ts.max(), 17)
W2 = np.array([svi_total_variance(ks2, *svi_params(sf)) for _, _, sf in slices])
Wg2 = np.array([[np.interp(t, Ts, W2[:, j]) for j in range(len(ks2))] for t in Tg2])
IV2 = np.sqrt(Wg2 / Tg2[:, None])
X = (ks2 - ks2.min()) / (ks2.max() - ks2.min()) * 100
Y = (Tg2 - Tg2.min()) / (Tg2.max() - Tg2.min()) * 80
Z = (IV2 - IV2.min()) / (IV2.max() - IV2.min()) * 35 + 5
lines = ["solid vol_surface"]


def facet(a, b, c):
    n = np.cross(np.subtract(b, a), np.subtract(c, a)); n = n / (np.linalg.norm(n) or 1)
    lines.append(f"facet normal {n[0]:.4f} {n[1]:.4f} {n[2]:.4f}")
    lines.append("outer loop")
    for v in (a, b, c):
        lines.append(f"vertex {v[0]:.3f} {v[1]:.3f} {v[2]:.3f}")
    lines.append("endloop"); lines.append("endfacet")


P = lambda i, j: (X[j], Y[i], Z[i, j])
B = lambda i, j: (X[j], Y[i], 0.0)
ni, nj = len(Tg2), len(ks2)
for i in range(ni - 1):
    for j in range(nj - 1):
        facet(P(i, j), P(i, j + 1), P(i + 1, j + 1)); facet(P(i, j), P(i + 1, j + 1), P(i + 1, j))
        facet(B(i, j), B(i + 1, j + 1), B(i, j + 1)); facet(B(i, j), B(i + 1, j), B(i + 1, j + 1))
for j in range(nj - 1):            # side walls make it a closed solid
    facet(B(0, j), P(0, j + 1), P(0, j)); facet(B(0, j), B(0, j + 1), P(0, j + 1))
    facet(B(ni - 1, j), P(ni - 1, j), P(ni - 1, j + 1)); facet(B(ni - 1, j), P(ni - 1, j + 1), B(ni - 1, j + 1))
for i in range(ni - 1):
    facet(B(i, 0), P(i, 0), P(i + 1, 0)); facet(B(i, 0), P(i + 1, 0), B(i + 1, 0))
    facet(B(i, nj - 1), P(i + 1, nj - 1), P(i, nj - 1)); facet(B(i, nj - 1), B(i + 1, nj - 1), P(i + 1, nj - 1))
lines.append("endsolid vol_surface")
open("assets/vol_surface.stl", "w").write("\n".join(lines) + "\n")
print("stl facets", sum(1 for l in lines if l.startswith("facet")))
