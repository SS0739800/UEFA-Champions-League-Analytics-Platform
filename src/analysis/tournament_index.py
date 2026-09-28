"""
Tournament Performance Index (TPI): a custom index for comparing clubs within a season.

This is our own index, not a UEFA metric and not an objective ranking. It mixes
results with how well a club controlled matches, adjusted a little for who it
played. Every component is shown next to the index so you can see why a club
is where it is, and the weights can be changed in the dashboard.

How it's built:
1. Work out six numbers per club-season (below).
2. Turn each into a z-score within that season: 0 is the average club,
   +1 is one standard deviation better. This puts goals, points and Elo on
   the same scale.
3. Take a weighted average of the z-scores.

Components and default weights:

  points_per_match       0.25  Results are what matter in the end.
  goal_diff_per_match    0.20  Separates narrow wins from dominant ones.
  sot_diff_per_match     0.20  Shots on target for minus against. Our stand-in
                               for xG difference: steadier than goals, but it
                               ignores shot quality.
  progression            0.15  How far the club got. Only used once the season
                               is finished, otherwise the weight is shared out.
  opponent_strength      0.10  Average pre-match Elo of opponents. Small weight
                               because the draw decides this, not the club.
  recent_form            0.10  Points per match over the club's last five games
                               of the season.

Limitations: with 6 to 17 games per season, one or two results can move a club
a long way. Z-scores assume the spread is similar across seasons, which isn't
quite true after the 2024-25 format change.
"""

import numpy as np
import pandas as pd

DEFAULT_WEIGHTS = {
    "points_per_match": 0.25,
    "goal_diff_per_match": 0.20,
    "sot_diff_per_match": 0.20,
    "progression": 0.15,
    "opponent_strength": 0.10,
    "recent_form": 0.10,
}

COMPONENT_LABELS = {
    "points_per_match": "Points / match",
    "goal_diff_per_match": "Goal difference / match",
    "sot_diff_per_match": "Shots on target difference / match",
    "progression": "Stage reached",
    "opponent_strength": "Opponent Elo",
    "recent_form": "Last 5 points / match",
}

STAGE_ORDER = {
    "group_stage": 1,
    "league_phase": 1,
    "knockout_playoff": 2,
    "round_of_16": 3,
    "quarter_final": 4,
    "semi_final": 5,
    "final": 6,
}

FORM_WINDOW = 5


def index_components(club_matches: pd.DataFrame, finished_seasons: set[int]) -> pd.DataFrame:
    """
    Raw component values for each club-season.

    club_matches is one row per club per finished match (v_club_matches).
    Progression is left empty for seasons that are still running.
    """
    frame = club_matches.sort_values("kickoff_utc").copy()
    frame["goal_diff"] = frame["goals_for"] - frame["goals_against"]
    frame["sot_diff"] = frame["shots_on_target"] - frame["shots_on_target_against"]
    frame["stage_order"] = frame["stage"].map(STAGE_ORDER)
    frame["won_final"] = (frame["stage"] == "final") & frame["won_match"]

    grouped = frame.groupby(["season_year", "club_id"])
    components = grouped.agg(
        matches=("match_id", "size"),
        points_per_match=("points", "mean"),
        goal_diff_per_match=("goal_diff", "mean"),
        sot_diff_per_match=("sot_diff", "mean"),
        opponent_strength=("opponent_elo_before", "mean"),
        furthest_stage=("stage_order", "max"),
        won_title=("won_final", "any"),
    )
    components["recent_form"] = grouped["points"].apply(lambda points: points.tail(FORM_WINDOW).mean())

    # Winning the final is one step further than reaching it.
    progression = components["furthest_stage"] + components["won_title"].astype(int)
    season_done = components.index.get_level_values("season_year").isin(list(finished_seasons))
    components["progression"] = np.where(season_done, progression, np.nan)

    return components.drop(columns=["furthest_stage"]).reset_index()


def zscore_within_season(components: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """z-score each column within its season. If every club has the same value, they all get 0."""
    def zscore(values: pd.Series) -> pd.Series:
        spread = values.std(ddof=0)
        if not spread or np.isnan(spread):
            return values * 0.0
        return (values - values.mean()) / spread

    return components.groupby("season_year")[columns].transform(zscore)


def tournament_index(components: pd.DataFrame, weights: dict[str, float] | None = None) -> pd.DataFrame:
    """
    Combine the components into the index.

    If a component is missing for a club (for example progression during a
    season that hasn't finished), its weight is shared among the others instead
    of treating it as zero.
    """
    weights = weights or DEFAULT_WEIGHTS
    names = list(weights)
    z_scores = zscore_within_season(components, names)

    weight_row = pd.Series(weights)
    available = z_scores.notna()
    weight_used = available.mul(weight_row, axis=1)
    total_weight = weight_used.sum(axis=1).replace(0, np.nan)

    result = components.copy()
    for name in names:
        result[f"{name}_z"] = z_scores[name]
    result["tpi"] = (z_scores.fillna(0) * weight_row).sum(axis=1) / total_weight
    result["tpi_rank"] = result.groupby("season_year")["tpi"].rank(ascending=False, method="min")
    return result.sort_values(["season_year", "tpi_rank"]).reset_index(drop=True)
