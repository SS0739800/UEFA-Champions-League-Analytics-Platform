import numpy as np
import pandas as pd
import pytest

from src.features.elo import calculate_elo
from src.features.match_features import (
    FEATURE_COLUMNS,
    build_match_features,
    first_leg_goal_difference,
    match_outcome,
)


@pytest.fixture
def club_stats():
    return pd.DataFrame({
        "match_id": [1, 1, 2, 2, 3, 3],
        "club_id": [10, 20, 20, 30, 10, 30],
        "shots_on_target": [6, 2, 4, 4, 1, 7],
    })


def features_for(matches, club_stats):
    return build_match_features(matches, club_stats, calculate_elo(matches)).set_index("match_id")


def test_first_match_has_no_form(simple_matches, club_stats):
    features = features_for(simple_matches, club_stats)
    assert np.isnan(features.loc[1, "form_points_diff"])
    assert features.loc[1, "experience_diff"] == 0


def test_features_only_use_earlier_matches(simple_matches, club_stats):
    """Changing a match's own result must not change that match's features."""
    changed = simple_matches.copy()
    changed.loc[changed["match_id"] == 3, ["home_goals", "home_goals_90"]] = 9

    original = features_for(simple_matches, club_stats)
    modified = features_for(changed, club_stats)

    pd.testing.assert_series_equal(original.loc[3, FEATURE_COLUMNS], modified.loc[3, FEATURE_COLUMNS])
    # ...but the next fixture does see it.
    assert original.loc[4, "goals_for_diff"] != modified.loc[4, "goals_for_diff"]


def test_form_uses_previous_results(simple_matches, club_stats):
    features = features_for(simple_matches, club_stats)
    # Before match 3: club 10 won 2-0 (3 pts), club 30 drew 1-1 (1 pt).
    assert features.loc[3, "form_points_diff"] == pytest.approx(3 - 1)
    assert features.loc[3, "goals_against_diff"] == pytest.approx(0 - 1)
    assert features.loc[3, "shots_on_target_for_diff"] == pytest.approx(6 - 4)


def test_scheduled_match_gets_features_but_no_outcome(simple_matches, club_stats):
    features = features_for(simple_matches, club_stats)
    assert pd.isna(features.loc[4, "outcome"])
    # Club 30 (home) beat club 10 3-0 in match 3, which is before match 4.
    assert features.loc[4, "form_points_diff"] > 0


def test_same_kickoff_matches_dont_see_each_other(simple_matches, club_stats):
    same_time = simple_matches.copy()
    same_time.loc[same_time["match_id"] == 2, "kickoff_utc"] = same_time.loc[0, "kickoff_utc"]
    features = features_for(same_time, club_stats)
    # Club 20 played match 1 at the same time as match 2, so it has no history for match 2.
    assert np.isnan(features.loc[2, "form_points_diff"])


def test_outcome_uses_the_90_minute_score():
    assert match_outcome(2, 1) == "H"
    assert match_outcome(1, 1) == "D"
    assert match_outcome(0, 3) == "A"
    assert match_outcome(None, 1) is None


def test_first_leg_result_seen_from_second_leg_home_side():
    matches = pd.DataFrame({
        "season_year": [2022, 2022, 2022],
        "stage": ["round_of_16"] * 3,
        "leg": [1, 2, None],
        "status": ["finished", "scheduled", "finished"],
        "home_club_id": [1, 2, 5],
        "away_club_id": [2, 1, 6],
        "home_goals": [3, None, 1],
        "away_goals": [1, None, 0],
    })
    # Club 2 lost the first leg 3-1 away, so it starts the second leg at home two goals down.
    assert first_leg_goal_difference(matches).tolist() == [0.0, -2.0, 0.0]
