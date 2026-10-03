"""Tools for telling a real edge from a lucky backtest. Shared by every research layer in this repo.

References:
  Bailey & Lopez de Prado (2012), "The Sharpe Ratio Efficient Frontier"  -> probabilistic Sharpe, min track record
  Bailey & Lopez de Prado (2014), "The Deflated Sharpe Ratio"            -> expected max Sharpe, deflated Sharpe
  Bailey, Borwein, Lopez de Prado & Zhu (2017), "The Probability of Backtest Overfitting" -> PBO via CSCV

Convention: functions take per-period returns and work in per-period Sharpe units internally.
`sharpe()` annualizes only for display.
"""
import itertools
import math
import numpy as np
from scipy.stats import norm, skew, kurtosis

EULER_GAMMA = 0.5772156649015329


def _clean(r):
    r = np.asarray(r, dtype=float)
    return r[np.isfinite(r)]


def sharpe(r, periods=252):
    """Annualized Sharpe ratio of per-period returns (risk-free assumed already subtracted)."""
    r = _clean(r)
    if len(r) < 2:
        return np.nan
    sd = r.std(ddof=1)
    return 0.0 if sd == 0 else r.mean() / sd * math.sqrt(periods)


def _sr_moments(r):
    r = _clean(r)
    sd = r.std(ddof=1)
    sr = 0.0 if sd == 0 else r.mean() / sd
    return sr, len(r), skew(r), kurtosis(r, fisher=False)


def probabilistic_sharpe(r, sr_benchmark=0.0):
    """Probability that the true per-period Sharpe exceeds sr_benchmark, given the sample's length,
    skewness and fat tails. sr_benchmark is per-period, not annualized."""
    sr, n, g3, g4 = _sr_moments(r)
    denom = 1 - g3 * sr + (g4 - 1) / 4 * sr ** 2
    if n < 3 or denom <= 0:
        return np.nan
    return float(norm.cdf((sr - sr_benchmark) * math.sqrt(n - 1) / math.sqrt(denom)))


def expected_max_sharpe(n_trials, sr_variance):
    """Expected best per-period Sharpe among n_trials strategies whose true Sharpe is zero,
    given the cross-sectional variance of their estimated Sharpe ratios."""
    if n_trials < 2 or sr_variance <= 0:
        return 0.0
    z1 = norm.ppf(1 - 1 / n_trials)
    z2 = norm.ppf(1 - 1 / (n_trials * math.e))
    return math.sqrt(sr_variance) * ((1 - EULER_GAMMA) * z1 + EULER_GAMMA * z2)


def deflated_sharpe(best_returns, trial_sharpes_per_period, n_trials=None):
    """Probabilistic Sharpe of the chosen strategy, benchmarked against the Sharpe you would expect
    from the luckiest of the strategies tried. Returns (dsr, sr0_per_period).
    n_trials defaults to the number of trials; pass a smaller effective count if trials are highly correlated."""
    t = _clean(trial_sharpes_per_period)
    n = n_trials or len(t)
    sr0 = expected_max_sharpe(n, t.var(ddof=1))
    return probabilistic_sharpe(best_returns, sr0), sr0


def min_track_record_length(r, sr_benchmark=0.0, confidence=0.95):
    """Number of periods needed before the observed Sharpe beats sr_benchmark at the given confidence."""
    sr, n, g3, g4 = _sr_moments(r)
    if sr <= sr_benchmark:
        return np.inf
    z = norm.ppf(confidence)
    return 1 + (1 - g3 * sr + (g4 - 1) / 4 * sr ** 2) * (z / (sr - sr_benchmark)) ** 2


def pbo_cscv(returns, n_blocks=16, max_combos=4000, seed=0):
    """Probability of backtest overfitting by combinatorially symmetric cross-validation.

    returns: T x N array, one column of per-period returns per strategy tried.
    Splits time into n_blocks; for each way of choosing half the blocks as in-sample, picks the strategy
    with the best in-sample Sharpe and records where it ranks out-of-sample. PBO is the share of splits
    in which the in-sample winner lands in the bottom half out-of-sample.

    Returns a dict with pbo, the logits of the winner's out-of-sample rank, and the in-sample and
    out-of-sample per-period Sharpe of each split's winner (for a degradation plot).
    """
    M = np.asarray(returns, dtype=float)
    M = np.where(np.isfinite(M), M, 0.0)
    T, N = M.shape
    if n_blocks % 2 or n_blocks < 4:
        raise ValueError("n_blocks must be even and at least 4")
    edges = np.array_split(np.arange(T), n_blocks)
    # Per-block sufficient statistics, so each split costs O(blocks x N) instead of O(T x N).
    bsum = np.stack([M[idx].sum(axis=0) for idx in edges])
    bsq = np.stack([(M[idx] ** 2).sum(axis=0) for idx in edges])
    bn = np.array([len(idx) for idx in edges], dtype=float)

    combos = list(itertools.combinations(range(n_blocks), n_blocks // 2))
    if max_combos and len(combos) > max_combos:
        rng = np.random.default_rng(seed)
        combos = [combos[i] for i in rng.choice(len(combos), size=max_combos, replace=False)]

    def sr_from(mask):
        n = bn[mask].sum()
        s = bsum[mask].sum(axis=0)
        q = bsq[mask].sum(axis=0)
        mean = s / n
        var = (q - n * mean ** 2) / (n - 1)
        sd = np.sqrt(np.clip(var, 0, None))
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(sd > 0, mean / sd, 0.0)

    logits, is_best, oos_best = [], [], []
    for c in combos:
        mask = np.zeros(n_blocks, dtype=bool)
        mask[list(c)] = True
        sr_is, sr_oos = sr_from(mask), sr_from(~mask)
        star = int(np.argmax(sr_is))
        rank = (sr_oos < sr_oos[star]).sum() + 0.5 * ((sr_oos == sr_oos[star]).sum() - 1) + 1  # 1..N
        w = rank / (N + 1)
        logits.append(math.log(w / (1 - w)))
        is_best.append(sr_is[star])
        oos_best.append(sr_oos[star])
    logits = np.array(logits)
    return {"pbo": float((logits <= 0).mean()), "logits": logits, "n_splits": len(combos),
            "is_sr_of_winner": np.array(is_best), "oos_sr_of_winner": np.array(oos_best)}
