"""Monte Carlo permutation tests (Timothy Masters, "Permutation and Randomization Tests for Trading System
Development").

The idea: when you search many strategy variants and keep the best, the winner's backtest is part real pattern
and part search luck. Shuffle the order of the daily returns and any real pattern (trend persistence,
mean reversion, seasonality) is destroyed, while the first and last price, the average return, volatility, skew
and the cross-market correlation on each day all stay the same. Rerun the *whole* search on many shuffled
histories: if the real winner beats nearly all the shuffled winners, the edge is unlikely to be search luck.

Two caveats worth stating whenever these are reported:
  - Shuffling also destroys volatility clustering and long memory. A strategy that lives on those can look
    better than it is (the test is optimistic for it), never worse.
  - Markets are shuffled with the same day order, so same-day correlations survive.

Functions
  permute_prices(px, start, rng)        one shuffled price history (a DataFrame, one column per market)
  permutation_pvalue(real, perms)       share of shuffled results at least as good as the real one
  run_permutations(fn, px, n, start)    fn(px) -> number, on n shuffled histories, in parallel
"""
import os
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd


def permute_prices(px, start=0, rng=None):
    """Shuffle daily log returns from return index `start` on (the same order for every column).

    Rows before `start` are untouched, which is how the walk-forward test keeps its first training window real.
    The total log return over the shuffled stretch is unchanged, so the last price is exactly the original."""
    rng = np.random.default_rng() if rng is None else rng
    logp = np.log(px.values.astype(float))
    lr = np.diff(logp, axis=0)
    idx = np.arange(len(lr))
    tail = idx[start:].copy()
    rng.shuffle(tail)
    idx[start:] = tail
    new = np.vstack([logp[:1], logp[:1] + np.cumsum(lr[idx], axis=0)])
    return pd.DataFrame(np.exp(new), index=px.index, columns=px.columns)


def permutation_pvalue(real, perms):
    """(1 + number of shuffled results >= real) / (1 + number of shuffles). The +1 counts the real history as one
    of the possible orderings, so the p-value is never exactly zero."""
    perms = np.asarray(perms, float)
    perms = perms[np.isfinite(perms)]
    return (1 + np.sum(perms >= real)) / (1 + len(perms))


_STATE = {}


def _init(fn, px, start):
    _STATE.update(fn=fn, px=px, start=start)


def _one(seed):
    rng = np.random.default_rng(seed)
    return _STATE["fn"](permute_prices(_STATE["px"], _STATE["start"], rng))


def run_permutations(fn, px, n=1000, start=0, seed=0, workers=None):
    """Evaluate fn on n shuffled versions of px, in parallel. fn must be a top-level (picklable) function."""
    seeds = np.random.SeedSequence(seed).generate_state(n)
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    if workers == 1:
        _init(fn, px, start)
        return np.array([_one(s) for s in seeds])
    with ProcessPoolExecutor(workers, initializer=_init, initargs=(fn, px, start)) as ex:
        return np.array(list(ex.map(_one, seeds, chunksize=max(1, n // (8 * workers)))))
