"""Option-implied probabilities for Bitcoin from Deribit, at a Kalshi settlement time.

Deribit's BTC options are inverse: quoted in BTC, worth max(S_T - K, 0) / S_T BTC at expiry, i.e. max(S_T - K, 0) in
USD. Their BTC premium times the expiry's forward (Deribit's `underlying_price`) is the undiscounted USD price of an
ordinary call on that forward, which is what `implied.bl.fit_surface` expects (Deribit uses a zero rate).

Deribit's options all expire at 08:00 UTC; Kalshi's BTC contracts settle on the hour (KXBTCD). So the smile of the
first Deribit expiry at or after the Kalshi settlement is moved back in time to it, keeping the smile's shape in
standard-deviation units: w_t(k) = (t / T1) * w_1(k / sqrt(t / T1)), so variance accrues evenly in calendar time and a
strike one standard deviation out keeps the same implied volatility. The forward is interpolated as S * (F1 / S)^(t / T1).
That ignores intraday and weekend variation in volatility; research/PREREGISTRATION_BTC.md states it as a limitation.
"""
import math
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from .bl import Surface, black_call, black_put, fit_surface

YEAR = 365 * 86400
MONTHS = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}


def parse_instrument(name):
    """BTC-10OCT26-84500-C -> (expiry datetime 08:00 UTC, strike, 'C')."""
    _, d, k, cp = name.split("-")
    day, mon, yr = int(d[:-5]), MONTHS[d[-5:-2]], 2000 + int(d[-2:])
    return datetime(yr, mon, day, 8, tzinfo=timezone.utc), float(k), cp


def deribit_surface(rows, expiry, now, min_strikes=8):
    """SVI surface for one Deribit expiry from a snapshot's option rows (collect/deribit_snapshot.py).

    Fitted to Deribit's mark implied volatility (the exchange's own smile, calibrated to its order book and used for
    margining) at every strike where the out-of-the-money option has a live bid or ask. Raw quotes are too coarse on
    the short expiries this needs: the tick is 0.0001 BTC (about $8), so beyond about 2% from the money a 12-hour
    option's bid-ask spread is as wide as its price. The forward is Deribit's (`underlying_price`); rate zero."""
    df = pd.DataFrame([r for r in rows if r.get("expiry") == expiry.isoformat()])
    if df.empty:
        raise ValueError(f"no options for {expiry}")
    F = float(df.underlying_price.median())
    df = df[((df.cp == "C") & (df.strike >= F)) | ((df.cp == "P") & (df.strike < F))]
    df = df[(df.bid.fillna(0) > 0) | (df.ask.fillna(0) > 0)]
    df = df[df.mark_iv.notna() & (df.mark_iv > 0)].sort_values("strike")
    if len(df) < min_strikes:
        raise ValueError(f"only {len(df)} quoted strikes")
    T = (expiry - now).total_seconds() / YEAR
    K, sig = df.strike.values.astype(float), df.mark_iv.values / 100
    is_c = df.cp.values == "C"
    px = np.where(is_c, black_call(F, K, T, sig, 1.0), black_put(F, K, T, sig, 1.0))
    C, P = np.where(is_c, px, np.nan), np.where(is_c, np.nan, px)
    # Price-space residuals relative to each price, so the cheap wings count as much as the money.
    return fit_surface(K, C, P, T, forward=(F, 1.0), weights=1.0 / np.maximum(px, 1.0))


def at_time(surf, t, spot):
    """The surface moved back to an earlier time t (years from now). With lam = t / T1 and r = sqrt(lam), raw SVI
    w_t(k) = lam * w_1(k / r) has parameters (lam*a, r*b, rho, r*m, r*s); the fitted range scales by r too."""
    lam = t / surf.T
    if lam >= 1:
        return surf
    a, b, rho, m, s = surf.params
    r = math.sqrt(lam)
    F = spot * (surf.F / spot) ** lam
    return Surface(F, 1.0, t, (lam * a, r * b, rho, r * m, r * s), (surf.k_min * r, surf.k_max * r))
