"""ROBUSTNESS (development sample only): is layer 11's 17% probability of backtest overfitting informative?

Kim (SSRN 6508779, item V5) and Witzany (2021): PBO says little when every configuration in the grid performs about
the same in-sample. Check: the spread of mean profit across the 64 grid cells (variance across cells) vs the same
spread when the signal days are circularly shifted through the calendar (a no-signal null with the same clustering).
If the real spread is no larger than the null's, the grid is flat and the PBO should be read as uninformative.
Also reported: the share of shifted grids whose BEST cell beats the real grid's best (a reality check on the search).
"""
import os, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research"))
import robust_layer11 as RB

q = RB.load()
days_all = q[q.h == 3].groupby("day").funding.first()
cuts = {fq: days_all.quantile(fq) for fq in RB.FQ_GRID if fq > 0}
D = RB.Days(q, 3)
masks = RB.grid_masks(D, cuts)
cells = [k for k, m in masks.items() if m.sum() >= 20]
real = np.array([D.score(masks[k]) for k in cells])
sims = np.column_stack([D.mc(masks[k]) for k in cells])          # rows: shifts, cols: cells (same shift per row)
var_real, var_null = real.var(), np.nanvar(sims, axis=1)
print(f"{len(cells)} cells. Variance of mean profit across cells: real {1e4 * var_real:.3f} (cents^2); "
      f"null median {1e4 * np.nanmedian(var_null):.3f}, 5th-95th percentile {1e4 * np.nanpercentile(var_null, 5):.3f} to "
      f"{1e4 * np.nanpercentile(var_null, 95):.3f}; real is at the {np.mean(var_null <= var_real):.0%} point of the null")
print(f"Best cell real {100 * real.max():+.2f}c; shifted grids whose best cell beats it: "
      f"{np.mean(np.nanmax(sims, axis=1) >= real.max()):.1%}")
print(f"Mean across cells real {100 * real.mean():+.2f}c; shifted grids with a higher average cell: "
      f"{np.mean(np.nanmean(sims, axis=1) >= real.mean()):.1%}")
