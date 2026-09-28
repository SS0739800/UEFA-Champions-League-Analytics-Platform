"""
Per-90 numbers for players, and how much to trust them.

Per-90 rates are handy for comparing players with different minutes, but they
get noisy fast. A sub who scores once in 30 minutes has 3.0 goals per 90,
which tells you almost nothing. Two things help here:

- a minimum-minutes filter (DEFAULT_MIN_MINUTES in config, three full games)
- an interval around each rate, so you can see how wide the uncertainty is
"""

import numpy as np
import pandas as pd
from scipy import stats

from src.config import DEFAULT_MIN_MINUTES


def per90(total, minutes):
    """Rate per 90 minutes. Players with no minutes get NaN instead of a division error."""
    total = np.asarray(total, dtype=float)
    minutes = np.asarray(minutes, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(minutes > 0, total * 90.0 / minutes, np.nan)


def poisson_rate_interval(count, minutes, confidence: float = 0.9) -> tuple[np.ndarray, np.ndarray]:
    """
    Exact Poisson interval for a per-90 rate.

    Goals are roughly Poisson, so for `count` goals in `minutes` minutes this
    gives a range of per-90 rates that fit the data. With few minutes the range
    is wide, which is the point.
    """
    count = np.asarray(count, dtype=float)
    nineties = np.asarray(minutes, dtype=float) / 90.0
    alpha = 1 - confidence

    lower = np.where(count > 0, stats.chi2.ppf(alpha / 2, 2 * count) / 2, 0.0)
    upper = stats.chi2.ppf(1 - alpha / 2, 2 * count + 2) / 2
    with np.errstate(divide="ignore", invalid="ignore"):
        return (
            np.where(nineties > 0, lower / nineties, np.nan),
            np.where(nineties > 0, upper / nineties, np.nan),
        )


def default_min_minutes(season_stats: pd.DataFrame) -> int:
    """
    Sensible minimum-minutes filter for a season.

    Normally three full games (270). Early in a season nobody has 270 yet, so
    drop to half of the most minutes anyone has played, in steps of 45.
    """
    if season_stats.empty:
        return 0
    most_minutes = int(season_stats["minutes"].max())
    if most_minutes >= 2 * DEFAULT_MIN_MINUTES:
        return DEFAULT_MIN_MINUTES
    return max(45, (most_minutes // 2) // 45 * 45)


def filter_by_minutes(season_stats: pd.DataFrame, min_minutes: int) -> pd.DataFrame:
    return season_stats[season_stats["minutes"] >= min_minutes]


def percentile_within(frame: pd.DataFrame, columns: list[str], group: str = "position_group") -> pd.DataFrame:
    """Percentile of each value among players in the same position group (0 to 100)."""
    ranked = frame.groupby(group)[columns].rank(pct=True) * 100
    return ranked.round(0)
