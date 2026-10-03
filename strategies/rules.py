"""The strategy library: simple, classic trading rules. Each returns a raw signal in {-1, 0, +1} per day,
computed only from prices up to and including that day."""
import itertools
import numpy as np
import pandas as pd


def momentum(p, look, skip):
    """Long if the price rose from `look` days ago to `skip` days ago, short if it fell."""
    return np.sign(p.shift(skip) / p.shift(look) - 1)


def ma_cross(p, fast, slow):
    """Long when the fast moving average is above the slow one."""
    return np.sign(p.rolling(fast).mean() - p.rolling(slow).mean())


def mean_reversion(p, win, z):
    """Bet against moves more than `z` standard deviations from the rolling mean."""
    s = (p - p.rolling(win).mean()) / p.rolling(win).std()
    return -np.sign(s) * (s.abs() > z)


def breakout(p, win):
    """Long after a close above the prior `win`-day high, short after a close below the prior low; hold until reversed."""
    hi, lo = p.rolling(win).max().shift(1), p.rolling(win).min().shift(1)
    sig = pd.Series(np.nan, index=p.index)
    sig[p > hi], sig[p < lo] = 1.0, -1.0
    return sig.ffill()


def rules():
    """Yield (name, function of prices) for every parameter combination in the library: 54 rules."""
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
