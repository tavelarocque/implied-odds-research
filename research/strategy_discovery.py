# %% [markdown]
# # How much of discovered alpha is real?
#
# Generate a few thousand simple trading rules on SPY and the nine sector ETFs, pick the best one the way a
# naive researcher would (highest in-sample Sharpe), then measure what happens out of sample, and how that
# depends on how many rules were searched. Every result goes through the shared robustness layer:
# deflated Sharpe ratio and probability of backtest overfitting (PBO).
#
# Run from the project root:  python3 research/strategy_discovery.py

# %%
import os, sys, itertools
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from robustness import sharpe, deflated_sharpe, pbo_cscv, probabilistic_sharpe

PRICES = os.path.join(ROOT, "data", "history", "etf", "prices.csv.gz")
OUT = os.path.join(ROOT, "research", "output", "strategy_discovery")
os.makedirs(OUT, exist_ok=True)
SPLIT = "2013-01-01"        # in-sample before, out-of-sample from here on
COST_BPS = 2.0              # per unit of turnover, each way
SEARCH_SIZES = [1, 3, 10, 30, 100, 300, 1000, 3000]
DRAWS = 400
rng = np.random.default_rng(11)

px = pd.read_csv(PRICES, index_col=0, parse_dates=True).dropna()
ret = px.pct_change().iloc[1:]
print(f"{len(px):,} days, {px.index[0].date()} to {px.index[-1].date()}, {px.shape[1]} ETFs")

# %% The strategy library. Signals use data up to day t; positions are applied to day t+1's return.
def momentum(p, look, skip):
    return np.sign(p.shift(skip) / p.shift(look) - 1)

def ma_cross(p, fast, slow):
    return np.sign(p.rolling(fast).mean() - p.rolling(slow).mean())

def mean_reversion(p, win, z):
    s = (p - p.rolling(win).mean()) / p.rolling(win).std()
    return -np.sign(s) * (s.abs() > z)

def breakout(p, win):
    hi, lo = p.rolling(win).max().shift(1), p.rolling(win).min().shift(1)
    sig = pd.Series(np.nan, index=p.index)
    sig[p > hi], sig[p < lo] = 1.0, -1.0
    return sig.ffill()

def rules():
    for look, skip in itertools.product([5, 10, 20, 40, 60, 120, 180, 252], [0, 5, 21]):
        if skip < look:
            yield f"mom_{look}_{skip}", lambda p, a=look, b=skip: momentum(p, a, b)
    for fast, slow in itertools.product([5, 10, 20, 50], [20, 50, 100, 200]):
        if fast < slow:
            yield f"ma_{fast}_{slow}", lambda p, a=fast, b=slow: ma_cross(p, a, b)
    for win, z in itertools.product([5, 10, 20, 60], [0.5, 1.0, 1.5, 2.0]):
        yield f"mr_{win}_{z}", lambda p, a=win, b=z: mean_reversion(p, a, b)
    for win in [10, 20, 55, 100, 252]:
        yield f"bo_{win}", lambda p, a=win: breakout(p, a)

cols, names = [], []
for tk in px.columns:
    p, r = px[tk], ret[tk]
    vol = (r.rolling(20).std() * np.sqrt(252)).reindex(r.index).bfill()
    for name, fn in rules():
        raw = fn(p).reindex(r.index).fillna(0.0)
        for mode in ("ls", "lo"):                         # long/short, or long/flat
            base = raw if mode == "ls" else raw.clip(lower=0)
            for sizing in ("flat", "vt"):                 # fixed size, or scaled to a 15% annual volatility target
                pos = base if sizing == "flat" else base * (0.15 / vol).clip(upper=2.0)
                pos = pos.shift(1).fillna(0.0)            # trade on the next day's return: no look-ahead
                pnl = pos * r - COST_BPS / 1e4 * pos.diff().abs().fillna(0.0)
                cols.append(pnl.values)
                names.append(f"{tk}:{name}:{mode}:{sizing}")
R = pd.DataFrame(np.column_stack(cols), index=ret.index, columns=names)
R = R.loc[R.index >= R.index[260]]                         # drop the warm-up year
ins_sd, oos_sd = R.loc[R.index < SPLIT].std(), R.loc[R.index >= SPLIT].std()
dead = (ins_sd == 0) | (oos_sd == 0)                         # rules that never traded in one of the periods
R = R.loc[:, ~dead]
print(f"dropped {int(dead.sum())} rules that never traded in-sample or out-of-sample")
print(f"{R.shape[1]:,} strategies x {R.shape[0]:,} days")

# %% In-sample vs out-of-sample Sharpe for every strategy
ins, oos = R.loc[R.index < SPLIT], R.loc[R.index >= SPLIT]
sr_is = ins.mean() / ins.std() * np.sqrt(252)
sr_oos = oos.mean() / oos.std() * np.sqrt(252)
corr = np.corrcoef(sr_is, sr_oos)[0, 1]
best = sr_is.idxmax()
bh = sharpe(ret["SPY"].loc[oos.index])
print(f"\nIn-sample {ins.index[0].date()} to {ins.index[-1].date()}, out-of-sample {oos.index[0].date()} to {oos.index[-1].date()}")
print(f"Correlation between in-sample and out-of-sample Sharpe across all strategies: {corr:.2f}")
print(f"Naive pick: {best}  in-sample Sharpe {sr_is[best]:.2f}  ->  out-of-sample {sr_oos[best]:.2f}   (SPY buy-and-hold OOS: {bh:.2f})")

# %% Deflated Sharpe of the naive pick: is its in-sample Sharpe impressive given how many rules were tried?
per_period_is = (ins.mean() / ins.std()).values
dsr, sr0 = deflated_sharpe(ins[best].values, per_period_is)
psr = probabilistic_sharpe(ins[best].values)
print(f"Probabilistic Sharpe (ignores the search): {psr:.3f}")
print(f"Deflated Sharpe (accounts for {R.shape[1]:,} trials): {dsr:.3f}; the luckiest-of-N benchmark is {sr0 * np.sqrt(252):.2f} annualized")
print("Note: the rules are correlated, so the effective number of independent trials is lower than the raw count.")

# %% Probability of backtest overfitting across the whole history
res = pbo_cscv(R.values, n_blocks=16, max_combos=3000)
print(f"\nPBO (CSCV, 16 blocks, {res['n_splits']} splits): {res['pbo']:.2f}")
print(f"Average annualized Sharpe of each split's in-sample winner: in-sample {np.mean(res['is_sr_of_winner']) * np.sqrt(252):.2f}, "
      f"out-of-sample {np.mean(res['oos_sr_of_winner']) * np.sqrt(252):.2f}")

# %% The key chart: the more you search, the better the backtest looks and the worse it holds up
rows = []
for k in SEARCH_SIZES:
    if k > R.shape[1]:
        continue
    for _ in range(DRAWS):
        pick = rng.choice(R.shape[1], size=k, replace=False)
        j = pick[np.argmax(sr_is.values[pick])]
        rows.append({"k": k, "is": sr_is.values[j], "oos": sr_oos.values[j]})
curve = pd.DataFrame(rows).groupby("k").agg(is_mean=("is", "mean"), oos_mean=("oos", "mean"),
                                             oos_p10=("oos", lambda s: s.quantile(.1)), oos_p90=("oos", lambda s: s.quantile(.9)))
curve["gap"] = curve.is_mean - curve.oos_mean
print("\nBest-of-k search (mean over random draws):")
print(curve.to_string(float_format=lambda x: f"{x:.2f}"))
curve.to_csv(os.path.join(OUT, "search_curve.csv"))
pd.DataFrame({"sr_is": sr_is, "sr_oos": sr_oos}).to_csv(os.path.join(OUT, "strategy_sharpes.csv.gz"))

fig, axes = plt.subplots(1, 3, figsize=(15, 4.4))
ax = axes[0]
ax.scatter(sr_is, sr_oos, s=4, alpha=.35, color="#4a6fa5")
ax.scatter([sr_is[best]], [sr_oos[best]], s=40, color="#b8520a", zorder=3, label="naive pick")
ax.axhline(0, color="#999", lw=1); ax.axvline(0, color="#999", lw=1)
ax.set_xlabel(f"In-sample Sharpe (to {SPLIT[:4]})"); ax.set_ylabel(f"Out-of-sample Sharpe ({SPLIT[:4]} on)")
ax.set_title(f"{R.shape[1]:,} strategies, correlation {corr:.2f}"); ax.legend(frameon=False, fontsize=8)
ax = axes[1]
ax.plot(curve.index, curve.is_mean, "o-", color="#b8520a", label="in-sample Sharpe of the winner")
ax.plot(curve.index, curve.oos_mean, "o-", color="#4a6fa5", label="its out-of-sample Sharpe")
ax.fill_between(curve.index, curve.oos_p10, curve.oos_p90, color="#4a6fa5", alpha=.15, label="out-of-sample 10th–90th pct")
ax.axhline(bh, color="#555", ls="--", lw=1, label="SPY buy-and-hold OOS")
ax.set_xscale("log"); ax.set_xlabel("Number of strategies searched"); ax.set_ylabel("Annualized Sharpe")
ax.set_title("Searching harder makes the backtest look better"); ax.legend(frameon=False, fontsize=8)
ax = axes[2]
ax.hist(res["logits"], bins=40, color="#4a6fa5", alpha=.8)
ax.axvline(0, color="#b8520a", lw=1.5)
ax.set_xlabel("Logit of the in-sample winner's out-of-sample rank"); ax.set_ylabel("CSCV splits")
ax.set_title(f"PBO = {res['pbo']:.2f} (share left of the line)")
fig.tight_layout()
fig.savefig(os.path.join(OUT, "overfitting.png"), dpi=160)
print(f"\nFigures and tables written to {OUT}")
