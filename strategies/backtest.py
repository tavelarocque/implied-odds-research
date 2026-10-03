"""Turn signals into positions and daily returns, with costs and no look-ahead.

Timing convention: a signal computed from the close of day t sets the position held over day t+1,
so it earns day t+1's return. Every position is shifted by one day to enforce that.
"""
import numpy as np
import pandas as pd
from .rules import rules

TARGET_VOL = 0.15


def positions(raw, r, mode="ls", sizing="flat"):
    """Position held on each day. mode: 'ls' long/short or 'lo' long/flat. sizing: 'flat' or 'vt' (15% vol target)."""
    base = raw.reindex(r.index).fillna(0.0)
    if mode == "lo":
        base = base.clip(lower=0)
    if sizing == "vt":
        vol = r.rolling(20).std() * np.sqrt(252)          # trailing only; undefined (no position) during warm-up
        base = base * (TARGET_VOL / vol).clip(upper=2.0)
    return base.shift(1).fillna(0.0)


def strategy_returns(pos, r, cost_bps=2.0):
    """Daily return of a position series after paying cost_bps per unit of turnover."""
    return pos * r - cost_bps / 1e4 * pos.diff().abs().fillna(0.0)


def build_library(px, cost_bps=2.0):
    """Every rule x mode x sizing on every column of px. Returns a DataFrame of daily strategy returns."""
    ret = px.pct_change().iloc[1:]
    cols, names = [], []
    for tk in px.columns:
        p, r = px[tk], ret[tk]
        for name, fn in rules():
            raw = fn(p)
            for mode in ("ls", "lo"):
                for sizing in ("flat", "vt"):
                    cols.append(strategy_returns(positions(raw, r, mode, sizing), r, cost_bps).values)
                    names.append(f"{tk}:{name}:{mode}:{sizing}")
    return pd.DataFrame(np.column_stack(cols), index=ret.index, columns=names), ret
