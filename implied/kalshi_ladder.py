"""Kalshi's daily S&P 500 range ladder (KXINX) as a probability distribution and as a set of tradable contracts.

A ladder is a list of mutually exclusive contracts that together cover every possible close:
    'less'     close <  cap          (lower tail)
    'between'  floor <= close <= cap (one 25-point range each)
    'greater'  close >  floor        (upper tail)
Exactly one pays $1. Kalshi has no single "S&P up today" contract in 2025-26, so P(close > K) must be built
from the ladder, and so must any trade that bets on it.
"""
import math
import numpy as np
import pandas as pd

KALSHI_FEE_RATE = 0.07          # taker fee per contract = rate * P * (1 - P); series fee_multiplier = 1


def kalshi_fee(p, contracts=None):
    """Taker fee in dollars per contract. With `contracts`, apply Kalshi's round-up to the cent on the order total."""
    raw = KALSHI_FEE_RATE * p * (1 - p)
    if contracts is None:
        return raw
    return math.ceil(round(raw * contracts * 100, 9)) / 100 / contracts


def make_ladder(rows):
    """rows: dicts with strike_type, floor_strike, cap_strike, bid, ask. Returns a DataFrame sorted low to high
    with numeric bounds lo/hi (None-free: -inf / +inf for the tails)."""
    df = pd.DataFrame(rows).copy()
    df["lo"] = np.where(df.strike_type == "less", -np.inf, pd.to_numeric(df.floor_strike, errors="coerce"))
    df["hi"] = np.where(df.strike_type == "greater", np.inf, pd.to_numeric(df.cap_strike, errors="coerce"))
    return df.sort_values("lo").reset_index(drop=True)


def ladder_mids(ladder, method="mid"):
    """Ladder prices normalized to sum to 1.

    method="mid": bid-ask midpoints. Simple, but a far-out range quoted 0 bid / 3c ask still gets 1.5c, and a
    dozen of those put phantom probability in the tails, pulling every estimate toward 50%.
    method="bid": bids only, i.e. what someone has actually committed to pay. Ranges nobody bids on get 0."""
    bid = ladder.bid.fillna(0)
    if method == "bid":
        w = bid
    elif method == "mid":
        w = (bid + ladder.ask.fillna(bid)) / 2    # no ask quote: nobody is selling it, value it at its bid (usually 0)
    else:
        raise ValueError("method must be 'mid' or 'bid'")
    total = w.sum()
    return w / total if total > 0 else w * np.nan


def prob_above(ladder, K, method="mid"):
    """P(close > K) implied by the ladder.

    The ladder gives the cumulative distribution exactly at every range edge. Between edges, a monotone cubic
    (PCHIP) through those points follows the curvature of the distribution; splitting the range containing K
    evenly instead is off by over a point when the distribution is narrow, as it is near the close."""
    p = ladder_mids(ladder, method).values
    if not np.all(np.isfinite(p)):
        return float("nan")                   # e.g. no bids anywhere on the ladder: no estimate
    lo, hi = ladder.lo.values, ladder.hi.values
    edges, cdf = [], []
    cum = 0.0
    for i in range(len(p)):
        cum += p[i]
        if np.isfinite(hi[i]):
            edges.append(hi[i])
            cdf.append(cum)
    edges, cdf = np.array(edges), np.array(cdf)
    if len(edges) < 2:
        return float(np.nan)
    if K <= edges[0]:                      # K inside the lower tail: the tail can't be split, count it as below K
        return float(1 - cdf[0])
    if K >= edges[-1]:                     # K inside the upper tail: count the tail as above K
        return float(1 - cdf[-1])
    from scipy.interpolate import PchipInterpolator
    keep = np.r_[True, np.diff(edges) > 0]
    F = PchipInterpolator(edges[keep], np.maximum.accumulate(cdf[keep]))
    return float(1 - F(K))


def basket(ladder, K, side):
    """Contracts that, bought together, pay $1 whenever close > K (side='up') or close < K (side='down').
    The range containing K is included, so the basket pays in every case the bet needs (and sometimes more)."""
    if side == "up":
        return ladder[ladder.hi > K]
    if side == "down":
        return ladder[ladder.lo < K]
    raise ValueError("side must be 'up' or 'down'")


def basket_cost(ladder, K, side, contracts=None):
    """Cost of buying one of each contract in the basket at the ask, plus Kalshi's taker fee.
    Returns (cost, n_contracts). cost is nan if any contract has no ask quote (it can't be bought)."""
    b = basket(ladder, K, side)
    if b.ask.isna().any() or len(b) == 0:
        return np.nan, len(b)
    fees = sum(kalshi_fee(a, contracts) for a in b.ask)
    return float(b.ask.sum() + fees), len(b)
