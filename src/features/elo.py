"""
Elo ratings built from Champions League results only.

This is a standard Elo system with a home advantage and a bigger update for
bigger wins (the same margin rule as the World Football Elo ratings). The
parameters are picked in notebooks/05_prediction_model.ipynb using the early
seasons only, and then left alone.

Limitations worth knowing:
- Domestic form is invisible. A club can be flying in its league and it won't show.
- Clubs we haven't seen before start at NEW_CLUB_RATING, which is a guess.
"""

import math

import pandas as pd

BASE_RATING = 1500.0
# Most clubs we haven't seen before came through qualifying, so start them
# a bit below the average club.
NEW_CLUB_RATING = 1450.0
K_FACTOR = 20.0
HOME_ADVANTAGE = 60.0
# At the start of each season, pull everyone a fifth of the way back to 1500.
# Squads change over the summer and old results matter less.
SEASON_REGRESSION = 0.2


def expected_score(rating_diff: float) -> float:
    """Chance-like score for the side with the rating advantage (a draw counts as half)."""
    return 1.0 / (1.0 + 10 ** (-rating_diff / 400.0))


def margin_multiplier(goal_difference: int) -> float:
    goal_difference = abs(goal_difference)
    if goal_difference <= 1:
        return 1.0
    if goal_difference == 2:
        return 1.5
    return (11 + goal_difference) / 8


def calculate_elo(
    matches: pd.DataFrame,
    k_factor: float = K_FACTOR,
    home_advantage: float = HOME_ADVANTAGE,
    new_club_rating: float = NEW_CLUB_RATING,
    season_regression: float = SEASON_REGRESSION,
) -> pd.DataFrame:
    """
    Walk through matches in kickoff order and record each club's rating before
    (and after) every match.

    Expects columns: match_id, season_year, kickoff_utc, status, home_club_id,
    away_club_id, home_goals, away_goals, is_neutral_venue.

    Scheduled matches get the club's current rating as elo_before and no elo_after.
    Returns one row per club per match.
    """
    ratings: dict[int, float] = {}
    current_season = None
    rows = []

    for match in matches.sort_values(["kickoff_utc", "match_id"]).itertuples():
        if match.season_year != current_season:
            # New season: everyone drifts back towards the average.
            ratings = {
                club: rating + season_regression * (BASE_RATING - rating) for club, rating in ratings.items()
            }
            current_season = match.season_year

        home = ratings.get(match.home_club_id, new_club_rating)
        away = ratings.get(match.away_club_id, new_club_rating)

        if match.status != "finished":
            rows.append((match.match_id, match.home_club_id, home, None))
            rows.append((match.match_id, match.away_club_id, away, None))
            continue

        advantage = 0.0 if match.is_neutral_venue else home_advantage
        home_expected = expected_score(home - away + advantage)

        goal_difference = int(match.home_goals - match.away_goals)
        home_actual = 1.0 if goal_difference > 0 else 0.5 if goal_difference == 0 else 0.0

        change = k_factor * margin_multiplier(goal_difference) * (home_actual - home_expected)
        ratings[match.home_club_id] = home + change
        ratings[match.away_club_id] = away - change

        rows.append((match.match_id, match.home_club_id, home, home + change))
        rows.append((match.match_id, match.away_club_id, away, away - change))

    return pd.DataFrame(rows, columns=["match_id", "club_id", "elo_before", "elo_after"])


def elo_log_loss(matches: pd.DataFrame, elo: pd.DataFrame, home_advantage: float = HOME_ADVANTAGE) -> float:
    """
    How well Elo's expected score matches what happened, treating a draw as half
    a win. Used to compare parameter choices. Lower is better.
    """
    finished = matches[matches["status"] == "finished"]
    before = elo.set_index(["match_id", "club_id"])["elo_before"]

    total, count = 0.0, 0
    for match in finished.itertuples():
        diff = before[(match.match_id, match.home_club_id)] - before[(match.match_id, match.away_club_id)]
        diff += 0.0 if match.is_neutral_venue else home_advantage
        expected = min(max(expected_score(diff), 1e-6), 1 - 1e-6)
        actual = 1.0 if match.home_goals > match.away_goals else 0.5 if match.home_goals == match.away_goals else 0.0
        total -= actual * math.log(expected) + (1 - actual) * math.log(1 - expected)
        count += 1
    return total / count
