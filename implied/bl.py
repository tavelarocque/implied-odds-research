"""Option-implied probabilities: Breeden-Litzenberger in practice.

The risk-neutral density of the index at expiry is the discounted second derivative of the call price
with respect to strike, and the probability of finishing above a strike is minus the discounted first
derivative. Differentiating raw quotes amplifies their noise, so the steps are:

  1. Estimate the forward F and discount factor DF from put-call parity (C - P = DF*F - DF*K).
  2. Convert out-of-the-money options to Black implied volatilities.
  3. Fit a smooth, arbitrage-light smile: raw SVI, w(k) = a + b*(rho*(k - m) + sqrt((k - m)^2 + s^2)),
     where w is total implied variance and k = log(K / F).
  4. Price calls on the fitted smile and differentiate those smooth prices.

A Kalshi range contract (a < S_T <= b) is a pair of digital options, so its option-implied probability is
P(S_T > a) - P(S_T > b). These are RISK-NEUTRAL probabilities: they include the premium investors pay for
protection, so they are not forecasts of real-world frequencies.
"""
import math
import numpy as np
from scipy.optimize import brentq, least_squares
from scipy.stats import norm


# ---------- Black-76 pricing on the forward ----------
def _d1d2(F, K, T, sigma):
    v = sigma * np.sqrt(T)
    d1 = (np.log(F / K) + 0.5 * v ** 2) / v
    return d1, d1 - v


def black_call(F, K, T, sigma, DF):
    d1, d2 = _d1d2(F, K, T, sigma)
    return DF * (F * norm.cdf(d1) - K * norm.cdf(d2))


def black_put(F, K, T, sigma, DF):
    d1, d2 = _d1d2(F, K, T, sigma)
    return DF * (K * norm.cdf(-d2) - F * norm.cdf(-d1))


def implied_vol(price, F, K, T, DF, is_call):
    """Black implied volatility, or nan when the price is outside no-arbitrage bounds."""
    intrinsic = DF * max(F - K, 0.0) if is_call else DF * max(K - F, 0.0)
    upper = DF * F if is_call else DF * K
    if not (intrinsic < price < upper):
        return np.nan
    f = (lambda s: black_call(F, K, T, s, DF) - price) if is_call else (lambda s: black_put(F, K, T, s, DF) - price)
    try:
        return brentq(f, 1e-4, 5.0, xtol=1e-8)
    except ValueError:
        return np.nan


# ---------- Step 1: forward and discount factor ----------
def estimate_forward(strikes, call_mid, put_mid, spot_guess=None, window=0.04):
    """Regress C - P on K over strikes near the money: intercept = DF*F, slope = -DF."""
    K = np.asarray(strikes, float)
    y = np.asarray(call_mid, float) - np.asarray(put_mid, float)
    ok = np.isfinite(y)
    if spot_guess is not None:
        ok &= np.abs(K / spot_guess - 1) < window
    if ok.sum() < 3:
        raise ValueError("not enough call/put pairs near the money to estimate the forward")
    slope, intercept = np.polyfit(K[ok], y[ok], 1)
    DF = -slope
    if not (0.9 < DF <= 1.0005):
        raise ValueError(f"implausible discount factor {DF:.5f} from put-call parity")
    return intercept / DF, min(DF, 1.0)


# ---------- Step 3: SVI smile ----------
def svi_total_variance(k, a, b, rho, m, s):
    return a + b * (rho * (k - m) + np.sqrt((k - m) ** 2 + s ** 2))


class Surface:
    """A fitted smile for one expiry. All probabilities are risk-neutral."""

    def __init__(self, F, DF, T, params, k_range):
        self.F, self.DF, self.T, self.params = F, DF, T, params
        self.k_min, self.k_max = k_range   # log-moneyness span of the quotes the fit used

    def sigma(self, K):
        k = np.log(np.asarray(K, float) / self.F)
        w = np.maximum(svi_total_variance(k, *self.params), 1e-10)
        return np.sqrt(w / self.T)

    def call(self, K):
        K = np.asarray(K, float)
        return black_call(self.F, K, self.T, self.sigma(K), self.DF)

    def prob_above(self, K, h=None):
        """P(S_T > K) = -(1/DF) dC/dK, by central difference on the smooth price curve."""
        K = np.asarray(K, float)
        h = h or self.F * 1e-4
        return -(self.call(K + h) - self.call(K - h)) / (2 * h) / self.DF

    def prob_between(self, lo=None, hi=None):
        """P(lo < S_T <= hi); either end may be None for an open-ended contract."""
        p_lo = 1.0 if lo is None else float(self.prob_above(lo))
        p_hi = 0.0 if hi is None else float(self.prob_above(hi))
        return p_lo - p_hi

    def density(self, K, h=None):
        K = np.asarray(K, float)
        h = h or self.F * 5e-4
        return (self.call(K + h) - 2 * self.call(K) + self.call(K - h)) / h ** 2 / self.DF

    def checks(self, n=4001, width=6.0):
        """Integrate the density over +/- width standard deviations: total mass ~1, mean ~F, no negative mass."""
        sd = float(self.sigma(self.F)) * math.sqrt(self.T) * self.F
        K = np.linspace(max(self.F - width * sd, 1.0), self.F + width * sd, n)
        q = self.density(K)
        dK = K[1] - K[0]
        return {"mass": float(q.sum() * dK), "mean": float((K * q).sum() * dK / max(q.sum() * dK, 1e-12)),
                "forward": self.F, "min_density": float(q.min()), "negative_mass": float(-q[q < 0].sum() * dK)}

    def in_fitted_range(self, K):
        return self.k_min <= math.log(K / self.F) <= self.k_max


def fit_surface(strikes, call_mid, put_mid, T, spot_guess=None, weights=None):
    """Fit forward, discount factor and an SVI smile to one expiry's mid quotes.
    weights: one per strike, ideally 1 / bid-ask spread (a quote's precision). Defaults to equal weights."""
    K = np.asarray(strikes, float)
    C, P = np.asarray(call_mid, float), np.asarray(put_mid, float)
    F, DF = estimate_forward(K, C, P, spot_guess=spot_guess)
    # Out-of-the-money side only: puts below the forward, calls above.
    iv = np.array([implied_vol(C[i], F, K[i], T, DF, True) if K[i] >= F else implied_vol(P[i], F, K[i], T, DF, False)
                   for i in range(len(K))])
    ok = np.isfinite(iv)
    if ok.sum() < 8:
        raise ValueError("fewer than 8 usable implied volatilities")
    k, w = np.log(K[ok] / F), iv[ok] ** 2 * T
    wt = np.ones_like(w) if weights is None else np.asarray(weights, float)[ok]

    def resid(p):
        a, b, rho, m, s = p
        return wt * (svi_total_variance(k, a, b, rho, m, s) - w) / max(w.mean(), 1e-12)

    x0 = [max(w.min() * 0.5, 1e-8), 0.1 * w.mean() / max(np.std(k), 1e-4), -0.5, 0.0, max(np.std(k), 1e-3)]
    lb = [-w.max(), 1e-8, -0.999, k.min() - 0.5, 1e-5]
    ub = [w.max() * 2, 10.0, 0.999, k.max() + 0.5, 5.0]
    best = None
    for rho0 in (-0.7, -0.3, 0.0):                 # a few starts guard against a poor local minimum
        x0[2] = rho0
        r = least_squares(resid, x0, bounds=(lb, ub), max_nfev=5000)
        if best is None or r.cost < best.cost:
            best = r
    # Refine in price space. A quote's noise is about its bid-ask spread in dollars, which is huge relative to
    # the price of a cheap far-out-of-the-money option; fitting volatilities directly would let those quotes
    # dominate. Price residuals scaled by the spread weight every quote by how precise it really is.
    otm_px = np.where(K[ok] >= F, C[ok], P[ok])
    is_call = K[ok] >= F
    Kok = K[ok]

    def resid_px(p):
        sig = np.sqrt(np.maximum(svi_total_variance(k, *p), 1e-10) / T)
        model = np.where(is_call, black_call(F, Kok, T, sig, DF), black_put(F, Kok, T, sig, DF))
        return wt * (model - otm_px)

    best = least_squares(resid_px, best.x, bounds=(lb, ub), max_nfev=5000)
    a, b, rho, m, s = best.x
    if a + b * s * math.sqrt(1 - rho ** 2) < 0:     # total variance must stay positive everywhere
        raise ValueError("SVI fit produced negative total variance")
    return Surface(F, DF, T, tuple(best.x), (float(k.min()), float(k.max())))


def surface_from_snapshot(options, expiry, T, spot_guess=None, root="SPXW", max_rel_spread=0.5):
    """Build a Surface from one snapshot's option rows (dicts from collect/options_snapshot.py).
    Uses PM-settled SPXW options, which settle on the same 4pm close as Kalshi's daily contracts."""
    import pandas as pd
    df = pd.DataFrame([o for o in options if o.get("expiry") == expiry and o.get("root") == root])
    if df.empty:
        raise ValueError(f"no {root} options for {expiry}")
    df = df[(df.bid > 0) & (df.ask > df.bid)].copy()
    df["mid"] = (df.bid + df.ask) / 2
    df = df[(df.ask - df.bid) / df.mid <= max_rel_spread]
    wide = df.pivot_table(index="strike", columns="cp", values="mid", aggfunc="mean").dropna()
    spr = df.assign(spread=df.ask - df.bid).pivot_table(index="strike", columns="cp", values="spread", aggfunc="mean").reindex(wide.index)
    weights = 1.0 / spr.mean(axis=1).clip(lower=0.05).values      # a quote is as precise as its spread
    return fit_surface(wide.index.values, wide["C"].values, wide["P"].values, T, spot_guess=spot_guess, weights=weights)
