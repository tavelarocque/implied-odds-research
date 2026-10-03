"""Project-wide research settings. Read this before changing any analysis.

FINAL HOLDOUT
Everything from FINAL_TEST_START onward is reserved for the final test of any trading rule or model
(layer 8). It was fixed on 2026-10-03, before any calibration result was looked at. Exploratory analyses
use only data before this date. Set UNLOCK_HOLDOUT=1 in the environment only for the single, final
evaluation, and record in the README when that happened.
"""
import os

FINAL_TEST_START = "2026-04-01"
HOLDOUT_UNLOCKED = os.environ.get("UNLOCK_HOLDOUT") == "1"


def exploratory(dates):
    """Boolean mask selecting rows that exploratory work may use. `dates` are ISO strings or datetimes."""
    import pandas as pd
    d = pd.to_datetime(pd.Series(dates).astype(str).str[:10])
    if HOLDOUT_UNLOCKED:
        return pd.Series(True, index=d.index).values
    return (d < pd.Timestamp(FINAL_TEST_START)).values
