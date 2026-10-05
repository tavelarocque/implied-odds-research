"""Discrete-time Hawkes model for activity counts per minute.

A Hawkes process is self-exciting: every event temporarily raises the rate of future events. In discrete time with an
exponential kernel, the expected count in minute t of a day is

    lambda_t = b_t + n * E_t,         E_t = phi * E_{t-1} + (1 - phi) * N_{t-1}

  b_t   baseline: the activity minute t normally has, e.g. the ramp into the close. log b is piecewise linear with
        knots every 15 minutes (K knots), fitted jointly with n and phi. K = 1 is a constant baseline.
  n     branching ratio: the expected number of extra events each event triggers (0 = none; must be < 1)
  phi   decay per minute; half-life = ln(0.5) / ln(phi) minutes, capped at HALF_LIFE_CAP
  E_t   exponentially weighted past activity; its kernel sums to 1, so n alone sets the strength

Counts are Poisson given lambda. Days are independent replicates sharing the parameters; each day starts with E = 0.

Two traps this design avoids, both shown in tests/test_hawkes.py:
  * A predictable intraday ramp looks like self-excitation if the baseline is constant (fitted n ~ 0.9 with none).
  * A baseline taken from raw averages by minute soaks up the activity that excitation caused and biases n low;
    so the baseline is fitted jointly. The half-life cap stops a very slow kernel from standing in for the ramp:
    self-excitation is a fast effect, slow drift is the baseline's job.
"""
import math
import numpy as np
from scipy.optimize import minimize
from scipy.signal import lfilter

HALF_LIFE_CAP = 30.0                       # minutes
PHI_MAX = 0.5 ** (1 / HALF_LIFE_CAP)
N_MAX = 0.999


def excitation(N, phi):
    """N: days x minutes counts. E[:, 0] = 0, E_t = phi E_{t-1} + (1 - phi) N_{t-1}."""
    return lfilter([0.0, 1 - phi], [1.0, -phi], np.asarray(N, float), axis=1)


def basis(T, K):
    """T x K hat functions on K equally spaced knots (piecewise-linear interpolation). K = 1: a constant."""
    if K == 1:
        return np.ones((T, 1))
    knots = np.linspace(0, T - 1, K)
    return np.stack([np.interp(np.arange(T), knots, np.eye(K)[j]) for j in range(K)], axis=1)


def n_knots(T, spacing=15):
    return max(2, int(round((T - 1) / spacing)) + 1)


def _sig(x):
    if x >= 0:
        return 1 / (1 + math.exp(-x))
    z = math.exp(x)                                        # stable for large negative x
    return z / (1 + z)


def _unpack(x):
    return N_MAX * _sig(x[0]), PHI_MAX * _sig(x[1]), x[2:]


def _nll_grad(x, N, B, fixed_n0=False):
    n, phi, th = _unpack(x)
    if fixed_n0:
        n = 0.0
    base = np.exp(B @ th)
    E = excitation(N, phi)
    lam = np.maximum(base[None, :] + n * E, 1e-12)
    nll = -(N * np.log(lam) - lam).sum()
    r = N / lam - 1                                        # d loglik / d lambda
    g = np.empty_like(x)
    g[2:] = -(B.T @ (r.sum(0) * base))
    if fixed_n0:
        g[0] = g[1] = 0.0
    else:
        g[0] = -(r * E).sum() * N_MAX * _sig(x[0]) * (1 - _sig(x[0]))
        h = 1e-6                                           # phi: central finite difference
        ll = []
        for d in (h, -h):
            E2 = excitation(N, PHI_MAX * _sig(x[1] + d))
            lam2 = np.maximum(base[None, :] + n * E2, 1e-12)
            ll.append(-(N * np.log(lam2) - lam2).sum())
        g[1] = (ll[0] - ll[1]) / (2 * h)
    return nll, g


def fit(N, K=None, spacing=15, n0_only=False):
    """Maximum likelihood. K=None: knots every `spacing` minutes; K=1: constant baseline.
    n0_only=True fits the baseline alone with n = 0 (the no-self-excitation null for a likelihood-ratio test).
    Returns dict(n, phi, half_life, loglik, baseline)."""
    N = np.asarray(N, float)
    T = N.shape[1]
    K = n_knots(T, spacing) if K is None else K
    B = basis(T, K)
    m = np.log(np.maximum(N.mean(0), 1e-3))
    th0 = np.linalg.lstsq(B, m, rcond=None)[0]
    starts = [(0.01, 0.5)] if n0_only else [(0.2, 0.5), (0.5, 0.8), (0.05, 0.9), (0.7, 0.3)]
    best = None
    for n0, p0 in starts:
        x0 = np.r_[math.log(n0 / (N_MAX - n0)), math.log(p0 / (1 - p0)),
                   th0 + math.log(1 - (0 if n0_only else n0))]
        r = minimize(_nll_grad, x0, args=(N, B, n0_only), jac=True, method="L-BFGS-B")
        if best is None or r.fun < best.fun:
            best = r
    n, phi, th = _unpack(best.x)
    if n0_only:
        n = 0.0
    return {"n": n, "phi": phi, "half_life": math.log(0.5) / math.log(phi), "loglik": -best.fun,
            "baseline": np.exp(B @ th)}


def simulate(days, b, n, phi, rng=None):
    """Simulate counts with baseline b (length T), for testing that fit() recovers known parameters."""
    rng = np.random.default_rng() if rng is None else rng
    T = len(b)
    N = np.zeros((days, T))
    E = np.zeros(days)
    for t in range(T):
        if t > 0:
            E = phi * E + (1 - phi) * N[:, t - 1]
        N[:, t] = rng.poisson(b[t] + n * E)
    return N


def _nll_grad_days(x, N, B):
    """Day effects: lambda_dt = exp(a_d) * b_t + n * E_dt, a_0 = 0. x = [n, phi, theta (K), a_1..a_{D-1}]."""
    D, T = N.shape
    K = B.shape[1]
    n, phi = N_MAX * _sig(x[0]), PHI_MAX * _sig(x[1])
    th, a = x[2:2 + K], np.r_[0.0, x[2 + K:]]
    base = np.exp(B @ th)
    scale = np.exp(a)
    bd = scale[:, None] * base[None, :]
    def ll_of(E):
        lam = np.maximum(bd + n * E, 1e-12)
        return -(N * np.log(lam) - lam).sum(), lam
    E = excitation(N, phi)
    nll, lam = ll_of(E)
    r = N / lam - 1
    g = np.empty_like(x)
    g[0] = -(r * E).sum() * N_MAX * _sig(x[0]) * (1 - _sig(x[0]))
    h = 1e-6
    g[1] = (ll_of(excitation(N, PHI_MAX * _sig(x[1] + h)))[0] - ll_of(excitation(N, PHI_MAX * _sig(x[1] - h)))[0]) / (2 * h)
    rb = r * bd
    g[2:2 + K] = -(B.T @ rb.sum(0))
    g[2 + K:] = -rb.sum(1)[1:]
    return nll, g


def fit_day_effects(N, spacing=15):
    """Like fit(), plus a multiplicative level per day. Busy days and quiet days with no clustering inside them
    otherwise look like self-excitation, because a shared baseline under-predicts a busy day all day long and the
    excitation term picks up the slack."""
    N = np.asarray(N, float)
    D, T = N.shape
    K = n_knots(T, spacing)
    B = basis(T, K)
    th0 = np.linalg.lstsq(B, np.log(np.maximum(N.mean(0), 1e-3)), rcond=None)[0]
    dm = np.maximum(N.mean(1), 1e-3)
    a0 = np.log(dm / dm[0])[1:]
    best = None
    for n0, p0 in ((0.2, 0.5), (0.5, 0.8), (0.05, 0.9), (0.7, 0.3)):
        x0 = np.r_[math.log(n0 / (N_MAX - n0)), math.log(p0 / (1 - p0)), th0 + math.log(1 - n0), a0]
        r = minimize(_nll_grad_days, x0, args=(N, B), jac=True, method="L-BFGS-B", options={"maxiter": 2000})
        if best is None or r.fun < best.fun:
            best = r
    n, phi = N_MAX * _sig(best.x[0]), PHI_MAX * _sig(best.x[1])
    return {"n": n, "phi": phi, "half_life": math.log(0.5) / math.log(phi), "loglik": -best.fun}
