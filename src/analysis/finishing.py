"""
Finishing numbers without xG.

We don't have shot locations or xG, so the best we can do is compare a player's
goals with what an average finisher would have scored from the same number of
shots on target. That's what "goals above average" means here:

    non-penalty goals - non-penalty shots on target * season average conversion

It ignores shot quality completely. A striker who only shoots from six yards
and one who shoots from 30 yards are treated the same, so read it as a rough
guide, not as a measure of finishing skill.
"""

import numpy as np
import pandas as pd


def season_conversion_rates(player_stats: pd.DataFrame) -> pd.DataFrame:
    """Competition-wide non-penalty goals per shot and per shot on target, by season."""
    totals = player_stats.groupby("season_year")[
        ["non_penalty_goals", "non_penalty_shots", "non_penalty_shots_on_target"]
    ].sum()
    return pd.DataFrame({
        "goals_per_shot": totals["non_penalty_goals"] / totals["non_penalty_shots"],
        "goals_per_shot_on_target": totals["non_penalty_goals"] / totals["non_penalty_shots_on_target"],
    }).reset_index()


def goals_above_average(player_stats: pd.DataFrame) -> pd.DataFrame:
    """
    Add expected goals *from average conversion* and the difference to actual goals.

    This is not xG. The column is called average_conversion_goals to keep that clear.
    """
    rates = season_conversion_rates(player_stats)
    merged = player_stats.merge(rates, on="season_year", how="left")
    merged["average_conversion_goals"] = (
        merged["non_penalty_shots_on_target"] * merged["goals_per_shot_on_target"]
    )
    merged["goals_above_average"] = merged["non_penalty_goals"] - merged["average_conversion_goals"]
    with np.errstate(divide="ignore", invalid="ignore"):
        merged["np_conversion"] = np.where(
            merged["non_penalty_shots"] > 0, merged["non_penalty_goals"] / merged["non_penalty_shots"], np.nan
        )
        merged["np_goals_per_shot_on_target"] = np.where(
            merged["non_penalty_shots_on_target"] > 0,
            merged["non_penalty_goals"] / merged["non_penalty_shots_on_target"],
            np.nan,
        )
    return merged


def team_finishing(club_season: pd.DataFrame) -> pd.DataFrame:
    """Shot conversion for clubs, plus the same numbers for shots they faced."""
    frame = club_season.copy()
    with np.errstate(divide="ignore", invalid="ignore"):
        frame["conversion"] = frame["goals_for"] / frame["shots"]
        frame["goals_per_shot_on_target"] = frame["goals_for"] / frame["shots_on_target"]
        frame["shot_accuracy"] = frame["shots_on_target"] / frame["shots"]
        frame["conceded_per_shot_on_target_faced"] = frame["goals_against"] / frame["shots_on_target_against"]
    return frame
