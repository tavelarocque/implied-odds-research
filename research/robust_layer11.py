"""ROBUSTNESS (development sample only): are layer 11's and 11b's rules on a plateau or a lonely spike?

Uses only layer 11's development quotes (research/output/explore_btc_sentiment.csv, contracts settling before
FINAL_TEST_START). Changes nothing pre-registered: this is a diagnostic of how fragile the chosen parameters were.

1. Parameter grid (3 hours out, mid >= 90c): Fear & Greed cut-off x funding cut-off (as a quantile of daily funding),
   signal = either one. Heat map of mean profit per contract from selling the downside long shot (after fees).
2. Monte Carlo on every cell: the cell's signal days are circularly shifted through the calendar 2,000 times (keeps
   how many signal days there are and how they cluster, breaks their link to outcomes). p = share of shifts with mean
   profit at least as high. Family-wise: the same shifts applied to the whole grid; how often does the BEST cell of a
   shifted grid beat the pre-registered cell's actual result (White's reality check, in its simplest form).
3. Plateau: how many of the pre-registered cell's neighbours are also positive.
4. Probability of backtest overfitting (Bailey, Borwein, Lopez de Prado and Zhu): days split into 8 time blocks; for all
   70 ways of choosing 4 blocks as in-sample, pick the best cell in-sample and see where it ranks out of sample.
5. Walk-forward: (a) the fixed pre-registered rule half-year by half-year; (b) a rule that re-picks the best grid cell
   on all earlier data at the start of each half-year, traded the next half-year.
6. More heat maps: Fear & Greed alone x hours before settlement; Fear & Greed x minimum mid; layer 11b's regime
   probability cut-off x hours before settlement.
Writes PNGs to research/output/robust/.
"""
import itertools, os, sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research"))
from config import FINAL_TEST_START
import explore_regimes as R

OUT = os.path.join(ROOT, "research", "output", "robust")
rng = np.random.default_rng(41)
N_MC = 2000
FG_GRID = [10, 15, 20, 25, 30, 35, 40, 50]
FQ_GRID = [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40]     # funding quantile; 0 = funding not used
PRE_FG, PRE_FUND = 25, 0.0000149


def load():
    q = pd.read_csv(os.path.join(ROOT, "research", "output", "explore_btc_sentiment.csv"))
    q = q[(q.side == "down") & (q.day < FINAL_TEST_START)].copy()
    d = pd.read_csv(os.path.join(ROOT, "data", "history", "crypto", "btc_daily.csv"), index_col=0, parse_dates=True)
    f, _ = R.walk_forward(d[d.index < FINAL_TEST_START], 2, 2017)
    f.index = (f.index + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    q = q.join(f[["s1"]], on="day")
    return q


class Days:
    """Day-level sums for one horizon and minimum mid, so any day-mask can be scored (and shifted) fast."""
    def __init__(self, q, h, mid_min=0.90):
        s = q[(q.h == h) & (q.mid >= mid_min)]
        g = s.groupby("day").agg(pnl=("pnl", "sum"), n=("pnl", "size"), lost=("y", lambda y: int((y == 0).sum())),
                                 fg=("fg", "first"), funding=("funding", "first"), s1=("s1", "first"))
        self.g = g.sort_index()
        self.P, self.N = self.g.pnl.values, self.g.n.values
        self.shifts = rng.integers(1, len(self.g), size=N_MC)

    def score(self, mask):
        n = self.N[mask].sum()
        return np.nan if n == 0 else self.P[mask].sum() / n

    def mc(self, mask):
        m = np.array([np.roll(mask, k) for k in self.shifts])
        n = m @ self.N
        with np.errstate(invalid="ignore", divide="ignore"):
            return (m @ self.P) / n


def heat(ax, M, xl, yl, title, fmt="{:+.1f}", ann=None, mark=None, cmap="RdBu", center=0.0, vmax=None):
    vmax = vmax or np.nanmax(np.abs(M - center))
    im = ax.imshow(M, cmap=cmap, vmin=center - vmax, vmax=center + vmax, aspect="auto", origin="lower")
    ax.set_xticks(range(len(xl))); ax.set_xticklabels(xl, fontsize=8)
    ax.set_yticks(range(len(yl))); ax.set_yticklabels(yl, fontsize=8)
    for i in range(M.shape[0]):
        for j in range(M.shape[1]):
            if np.isfinite(M[i, j]):
                t = fmt.format(M[i, j]) + ("" if ann is None else ann[i][j])
                ax.text(j, i, t, ha="center", va="center", fontsize=7)
    if mark is not None:
        ax.add_patch(plt.Rectangle((mark[1] - 0.5, mark[0] - 0.5), 1, 1, fill=False, lw=2.5, ec="black"))
    ax.set_title(title, fontsize=10)
    return im


def grid_masks(D, fund_cuts):
    masks = {}
    for i, fq in enumerate(FQ_GRID):
        for j, fg in enumerate(FG_GRID):
            m = (D.g.fg <= fg).values
            if fq > 0:
                m = m | (D.g.funding <= fund_cuts[fq]).values
            masks[(i, j)] = m
    return masks


def main():
    os.makedirs(OUT, exist_ok=True)
    q = load()
    days_all = q[q.h == 3].groupby("day").funding.first()
    fund_cuts = {fq: days_all.quantile(fq) for fq in FQ_GRID if fq > 0}
    pre_fq = (days_all <= PRE_FUND).mean()
    print(f"Development sample: {q.day.nunique()} days; the pre-registered funding cut-off {PRE_FUND} is the "
          f"{pre_fq:.0%} quantile of daily funding (grid row 0.20 is {fund_cuts[0.20]:.7f})")

    # 1-3. grid, Monte Carlo per cell, family-wise check, plateau
    D = Days(q, 3)
    masks = grid_masks(D, fund_cuts)
    M = np.full((len(FQ_GRID), len(FG_GRID)), np.nan); Pv = M.copy(); Nd = M.copy()
    mc_all = {}
    for (i, j), m in masks.items():
        M[i, j] = 100 * D.score(m); Nd[i, j] = m.sum()
        sim = D.mc(m); mc_all[(i, j)] = sim
        Pv[i, j] = np.mean(sim >= D.score(m))
    pre = (FQ_GRID.index(0.20), FG_GRID.index(25))
    ok = [k for k in masks if Nd[k] >= 20]
    best_sim = np.nanmax(np.column_stack([mc_all[k] for k in ok]), axis=1)
    fw_p = np.mean(best_sim >= M[pre] / 100)
    best_cell = max(ok, key=lambda k: M[k])
    nb = [(pre[0] + a, pre[1] + b) for a in (-1, 0, 1) for b in (-1, 0, 1) if (a or b)
          and 0 <= pre[0] + a < len(FQ_GRID) and 0 <= pre[1] + b < len(FG_GRID)]
    print(f"\n1-3. Grid at 3h, mid >= 90c ({len(ok)} of {len(masks)} cells with 20+ signal days)")
    print(f"   pre-registered cell (F&G <= 25 or funding bottom 20%): {M[pre]:+.2f}c on {int(Nd[pre])} days, "
          f"Monte Carlo p {Pv[pre]:.3f}; family-wise p (best shifted cell beats it) {fw_p:.3f}")
    print(f"   best cell: F&G <= {FG_GRID[best_cell[1]]}, funding q {FQ_GRID[best_cell[0]]:.2f}: {M[best_cell]:+.2f}c")
    print(f"   cells positive: {np.mean(M[np.isfinite(M)] > 0):.0%}; with Monte Carlo p < 0.05: "
          f"{np.mean([Pv[k] < 0.05 for k in ok]):.0%} of cells with 20+ days")
    print(f"   neighbours of the pre-registered cell positive: {sum(M[k] > 0 for k in nb)} of {len(nb)}; "
          f"p < 0.05: {sum(Pv[k] < 0.05 for k in nb)} of {len(nb)}; range {min(M[k] for k in nb):+.2f} to {max(M[k] for k in nb):+.2f}c")
    base = 100 * D.P.sum() / D.N.sum()
    print(f"   all days (no signal): {base:+.2f}c per contract")

    fig, axs = plt.subplots(1, 2, figsize=(14, 5.5))
    ann = [[f"\n{int(Nd[i, j])}d" + ("*" if Pv[i, j] < 0.05 else "") for j in range(len(FG_GRID))] for i in range(len(FQ_GRID))]
    yl = ["off" if fq == 0 else f"{int(100 * fq)}%" for fq in FQ_GRID]
    im = heat(axs[0], M, [f"<={x}" for x in FG_GRID], yl, "Selling downside long shots 3h out: cents per contract after fees\n"
              "(d = signal days, * = Monte Carlo p < 0.05; box = pre-registered)", ann=ann, mark=pre)
    plt.colorbar(im, ax=axs[0]); axs[0].set_xlabel("Fear & Greed cut-off"); axs[0].set_ylabel("funding cut-off (bottom quantile)")
    im = heat(axs[1], Pv, [f"<={x}" for x in FG_GRID], yl, "Monte Carlo p-value per cell (circular shifts of signal days)",
              fmt="{:.2f}", mark=pre, cmap="viridis_r", center=0.5, vmax=0.5)
    plt.colorbar(im, ax=axs[1]); axs[1].set_xlabel("Fear & Greed cut-off")
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "layer11_grid.png"), dpi=140); plt.close(fig)

    # 4. probability of backtest overfitting (CSCV)
    blocks = np.array_split(np.arange(len(D.g)), 8)
    cells = ok
    logits = []
    for ins in itertools.combinations(range(8), 4):
        im_ = np.zeros(len(D.g), bool); im_[np.concatenate([blocks[b] for b in ins])] = True
        sc_in = [D.score(masks[k] & im_) for k in cells]
        sc_out = np.array([D.score(masks[k] & ~im_) for k in cells])
        b = int(np.nanargmax(sc_in))
        if not np.isfinite(sc_out[b]):
            continue
        rank = (np.sum(sc_out[np.isfinite(sc_out)] < sc_out[b]) + 0.5) / (np.isfinite(sc_out).sum() + 1)
        logits.append(np.log(rank / (1 - rank)))
    pbo = np.mean(np.array(logits) <= 0)
    print(f"\n4. Probability of backtest overfitting over the {len(cells)}-cell grid: {pbo:.0%} "
          f"({len(logits)} splits; below 50% means the in-sample best usually stays above median out of sample)")

    # 5. walk-forward
    D.g["half"] = [f"{d[:4]}H{1 if int(d[5:7]) <= 6 else 2}" for d in D.g.index]
    pre_m = masks[pre]
    print("\n5a. Fixed pre-registered rule, by half-year (3h):")
    for hf, idx in D.g.groupby("half").indices.items():
        sel = np.zeros(len(D.g), bool); sel[idx] = True; s = sel & pre_m
        n = D.N[s].sum()
        print(f"   {hf}: {int(s.sum())} signal days, {int(n)} trades, "
              + (f"{100 * D.P[s].sum() / n:+.2f}c, {int(D.g.lost.values[s].sum())} paid out" if n else "no trades"))
    print("5b. Re-pick the best cell on all earlier data, trade the next half-year:")
    halves = sorted(D.g.half.unique())
    tot = {"adaptive": [0, 0], "fixed": [0, 0]}
    for k, hf in enumerate(halves[1:], 1):
        past = D.g.half.isin(halves[:k]).values; nxt = (D.g.half == hf).values
        cand = [c for c in masks if (masks[c] & past).sum() >= 10]
        if not cand:
            continue
        c = max(cand, key=lambda c: D.score(masks[c] & past))
        for name, m in (("adaptive", masks[c] & nxt), ("fixed", pre_m & nxt)):
            tot[name][0] += D.P[m].sum(); tot[name][1] += D.N[m].sum()
        n = D.N[masks[c] & nxt].sum()
        print(f"   {hf}: picked F&G <= {FG_GRID[c[1]]}, funding q {FQ_GRID[c[0]]:.2f}; next half "
              + (f"{100 * D.P[masks[c] & nxt].sum() / n:+.2f}c on {int(n)} trades" if n else "no trades"))
    for name, (p, n) in tot.items():
        print(f"   {name} total out of sample: " + (f"{100 * p / n:+.2f}c per contract on {int(n)} trades" if n else "none"))

    # 6. more heat maps
    fig, axs = plt.subplots(1, 3, figsize=(18, 5))
    H = [1, 3, 6]
    A = np.full((len(H), len(FG_GRID)), np.nan); An = [["" for _ in FG_GRID] for _ in H]
    for i, h in enumerate(H):
        Dh = Days(q, h)
        for j, fg in enumerate(FG_GRID):
            m = (Dh.g.fg <= fg).values
            A[i, j] = 100 * Dh.score(m)
            An[i][j] = f"\n{int(m.sum())}d" + ("*" if np.mean(Dh.mc(m) >= Dh.score(m)) < 0.05 else "")
    im = heat(axs[0], A, [f"<={x}" for x in FG_GRID], [f"{h}h" for h in H], "Fear & Greed alone x hours before settlement",
              ann=An, mark=(1, FG_GRID.index(25)))
    plt.colorbar(im, ax=axs[0]); axs[0].set_xlabel("Fear & Greed cut-off")
    MIDS = [0.90, 0.92, 0.94, 0.96]
    B = np.full((len(MIDS), len(FG_GRID)), np.nan); Bn = [["" for _ in FG_GRID] for _ in MIDS]
    for i, mm in enumerate(MIDS):
        Dm = Days(q, 3, mm)
        for j, fg in enumerate(FG_GRID):
            m = (Dm.g.fg <= fg).values | (Dm.g.funding <= PRE_FUND).values
            B[i, j] = 100 * Dm.score(m)
            Bn[i][j] = f"\n{int(Dm.N[m].sum())}t"
    im = heat(axs[1], B, [f"<={x}" for x in FG_GRID], [f">={int(100 * x)}c" for x in MIDS],
              "Minimum mid x Fear & Greed (with funding), 3h\n(t = trades)", ann=Bn, mark=(0, FG_GRID.index(25)))
    plt.colorbar(im, ax=axs[1]); axs[1].set_xlabel("Fear & Greed cut-off")
    TH = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    C = np.full((len(H), len(TH)), np.nan); Cn = [["" for _ in TH] for _ in H]
    for i, h in enumerate(H):
        Dh = Days(q, h)
        for j, t in enumerate(TH):
            m = (Dh.g.s1 > t).values
            C[i, j] = 100 * Dh.score(m)
            Cn[i][j] = f"\n{int(m.sum())}d" + ("*" if np.mean(Dh.mc(m) >= Dh.score(m)) < 0.05 else "")
    im = heat(axs[2], C, [f">{t}" for t in TH], [f"{h}h" for h in H], "Layer 11b: turbulent-state probability cut-off x hours",
              ann=Cn, mark=(1, TH.index(0.5)))
    plt.colorbar(im, ax=axs[2]); axs[2].set_xlabel("turbulent probability cut-off")
    fig.suptitle("Cents per contract from selling the downside long shot, after fees (development sample; box = pre-registered)")
    fig.tight_layout(); fig.savefig(os.path.join(OUT, "layer11_more.png"), dpi=140); plt.close(fig)
    print("\n6. Heat maps of Fear & Greed x hours, x minimum mid, and 11b's cut-off x hours ->", os.path.relpath(OUT, ROOT))
    for name, X_, rows, cols in (("F&G x hours", A, [f"{h}h" for h in H], FG_GRID), ("11b cut-off x hours", C, [f"{h}h" for h in H], TH)):
        print(f"   {name}: " + "; ".join(f"{r}: " + " ".join(f"{v:+.1f}" for v in X_[i]) for i, r in enumerate(rows)))


if __name__ == "__main__":
    main()
