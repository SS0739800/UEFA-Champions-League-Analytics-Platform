"""
Pre-match features for the outcome model.

Every feature for a match only uses matches that kicked off before it. The
rolling form numbers are worked out after each finished match, and then each
fixture picks up the latest values from *before* its kickoff (merge_asof with
allow_exact_matches=False), so a match can never see its own result.

Form carries across seasons on purpose: a club's last five UCL games might
include last spring's knockouts. Domestic games aren't in the data, so "form"
here only means Champions League form.
"""

import numpy as np
import pandas as pd

FORM_WINDOW = 5

FEATURE_COLUMNS = [
    "elo_diff",
    "form_points_diff",
    "goals_for_diff",
    "goals_against_diff",
    "shots_on_target_for_diff",
    "shots_on_target_against_diff",
    "experience_diff",
    "is_neutral_venue",
    "is_knockout",
    "first_leg_goal_diff",
]

OUTCOMES = ["H", "D", "A"]


def club_match_rows(matches: pd.DataFrame, club_stats: pd.DataFrame) -> pd.DataFrame:
    """One row per club per finished match with the numbers we roll over."""
    finished = matches[matches["status"] == "finished"]
    sides = []
    for side, other in (("home", "away"), ("away", "home")):
        sides.append(pd.DataFrame({
            "match_id": finished["match_id"],
            "kickoff_utc": finished["kickoff_utc"],
            "club_id": finished[f"{side}_club_id"],
            "opponent_id": finished[f"{other}_club_id"],
            "goals_for": finished[f"{side}_goals"],
            "goals_against": finished[f"{other}_goals"],
        }))
    rows = pd.concat(sides, ignore_index=True)

    rows["points"] = np.select(
        [rows["goals_for"] > rows["goals_against"], rows["goals_for"] == rows["goals_against"]], [3, 1], 0
    )

    shots = club_stats[["match_id", "club_id", "shots_on_target"]]
    rows = rows.merge(shots, on=["match_id", "club_id"], how="left")
    rows = rows.merge(
        shots.rename(columns={"club_id": "opponent_id", "shots_on_target": "shots_on_target_against"}),
        on=["match_id", "opponent_id"],
        how="left",
    )
    return rows.sort_values(["kickoff_utc", "match_id"]).reset_index(drop=True)


def rolling_form(club_rows: pd.DataFrame, window: int = FORM_WINDOW) -> pd.DataFrame:
    """
    Each club's form over its last `window` matches, measured *after* each match.

    The first match has a value based on one game. Matches with missing shot
    data are skipped by the mean rather than counted as zero.
    """
    columns = ["points", "goals_for", "goals_against", "shots_on_target", "shots_on_target_against"]
    grouped = club_rows.groupby("club_id")[columns]
    form = grouped.rolling(window, min_periods=1).mean().reset_index(level=0, drop=True)
    form.columns = [f"form_{column}" for column in columns]

    result = club_rows[["club_id", "kickoff_utc"]].join(form)
    result["previous_matches"] = club_rows.groupby("club_id").cumcount() + 1
    return result


def form_before_kickoff(fixtures: pd.DataFrame, form: pd.DataFrame, side: str) -> pd.DataFrame:
    """Attach the latest form from strictly before each fixture's kickoff."""
    left = fixtures[["match_id", "kickoff_utc", f"{side}_club_id"]].rename(columns={f"{side}_club_id": "club_id"})
    merged = pd.merge_asof(
        left.sort_values("kickoff_utc"),
        form.sort_values("kickoff_utc"),
        on="kickoff_utc",
        by="club_id",
        # This is the important bit: don't use a row from the same kickoff.
        allow_exact_matches=False,
        direction="backward",
    )
    merged["previous_matches"] = merged["previous_matches"].fillna(0)
    return merged.drop(columns=["kickoff_utc", "club_id"]).add_prefix(f"{side}_").rename(
        columns={f"{side}_match_id": "match_id"}
    )


def first_leg_goal_difference(matches: pd.DataFrame) -> pd.Series:
    """
    For second legs, how the first leg went from the second-leg home side's view.
    It's known before kickoff and changes how teams play. 0 for everything else.
    """
    first_legs = matches[(matches["leg"] == 1) & (matches["status"] == "finished")]
    # In the second leg the first-leg away team is at home.
    lookup = {
        (row.season_year, row.stage, row.away_club_id, row.home_club_id): row.away_goals - row.home_goals
        for row in first_legs.itertuples()
    }

    def lookup_row(row):
        if row.leg != 2:
            return 0.0
        return lookup.get((row.season_year, row.stage, row.home_club_id, row.away_club_id), np.nan)

    return pd.Series([lookup_row(row) for row in matches.itertuples()], index=matches.index)


def match_outcome(home_goals, away_goals) -> str | None:
    if pd.isna(home_goals) or pd.isna(away_goals):
        return None
    if home_goals > away_goals:
        return "H"
    if home_goals == away_goals:
        return "D"
    return "A"


def build_match_features(matches: pd.DataFrame, club_stats: pd.DataFrame, elo: pd.DataFrame) -> pd.DataFrame:
    """
    One row per match with the model features and the 90-minute outcome.

    matches needs: match_id, season_year, stage, leg, kickoff_utc, status,
    home_club_id, away_club_id, home_goals, away_goals, home_goals_90,
    away_goals_90, is_neutral_venue.
    """
    matches = matches.sort_values(["kickoff_utc", "match_id"]).reset_index(drop=True)
    form = rolling_form(club_match_rows(matches, club_stats))

    features = matches[["match_id", "season_year", "stage", "kickoff_utc", "status",
                        "home_club_id", "away_club_id"]].copy()
    features = features.merge(form_before_kickoff(matches, form, "home"), on="match_id")
    features = features.merge(form_before_kickoff(matches, form, "away"), on="match_id")

    elo_lookup = elo.set_index(["match_id", "club_id"])["elo_before"]
    home_elo = elo_lookup.reindex(list(zip(features["match_id"], features["home_club_id"]))).to_numpy()
    away_elo = elo_lookup.reindex(list(zip(features["match_id"], features["away_club_id"]))).to_numpy()

    features["elo_diff"] = home_elo - away_elo
    features["form_points_diff"] = features["home_form_points"] - features["away_form_points"]
    features["goals_for_diff"] = features["home_form_goals_for"] - features["away_form_goals_for"]
    features["goals_against_diff"] = features["home_form_goals_against"] - features["away_form_goals_against"]
    features["shots_on_target_for_diff"] = (
        features["home_form_shots_on_target"] - features["away_form_shots_on_target"]
    )
    features["shots_on_target_against_diff"] = (
        features["home_form_shots_on_target_against"] - features["away_form_shots_on_target_against"]
    )
    # log1p so the difference between 0 and 10 previous games matters more than 60 vs 70.
    features["experience_diff"] = np.log1p(features["home_previous_matches"]) - np.log1p(
        features["away_previous_matches"]
    )
    features["is_neutral_venue"] = matches["is_neutral_venue"].astype(int).to_numpy()
    features["is_knockout"] = (~matches["stage"].isin(["group_stage", "league_phase"])).astype(int).to_numpy()
    features["first_leg_goal_diff"] = first_leg_goal_difference(matches).to_numpy()

    features["outcome"] = [
        match_outcome(home, away) for home, away in zip(matches["home_goals_90"], matches["away_goals_90"])
    ]

    keep = ["match_id", "season_year", "stage", "kickoff_utc", "status", "home_club_id", "away_club_id"]
    return features[keep + FEATURE_COLUMNS + ["outcome"]]
