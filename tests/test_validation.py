"""Validation tests, built from one small made-up match that passes and then broken on purpose."""

import numpy as np
import pandas as pd
import pytest

from src.validation.checks import blank_missing_stats, run_checks, stat_coverage_by_season
from src.validation.schemas import validate_tables


@pytest.fixture
def tables():
    matches = pd.DataFrame({
        "espn_event_id": [1],
        "season_year": [2022],
        "stage": ["group_stage"],
        "group_name": pd.Series(["A"], dtype="str"),
        "leg": [np.nan],
        "kickoff_utc": [pd.Timestamp("2022-09-14 19:00", tz="UTC")],
        "status": ["finished"],
        "home_espn_id": [100],
        "away_espn_id": [200],
        "home_goals": [2.0],
        "away_goals": [1.0],
        "home_goals_90": [2.0],
        "away_goals_90": [1.0],
        "went_to_extra_time": [False],
        "is_neutral_venue": [False],
        "attendance": [40000.0],
    })
    clubs = pd.DataFrame({"espn_team_id": [100, 200], "name": ["Home FC", "Away FC"],
                          "short_name": ["Home", "Away"]})
    players = pd.DataFrame({"espn_athlete_id": [1, 2], "full_name": ["Player One", "Player Two"]})

    stat_names = ["possession_pct", "shots", "shots_on_target", "blocked_shots", "passes", "passes_completed",
                  "crosses", "crosses_completed", "long_balls", "long_balls_completed", "tackles", "tackles_won",
                  "interceptions", "clearances", "corners", "fouls", "offsides", "yellow_cards", "red_cards",
                  "saves"]
    club_stats = pd.DataFrame([
        {"espn_event_id": 1, "espn_team_id": 100, **dict.fromkeys(stat_names, 5.0), "possession_pct": 55.0},
        {"espn_event_id": 1, "espn_team_id": 200, **dict.fromkeys(stat_names, 5.0), "possession_pct": 45.0},
    ])

    base_player = {"espn_event_id": 1, "position_group": "FWD", "is_starter": True, "minute_on": 0,
                   "minute_off": 90, "minutes_played": 90, "assists": 0, "shots": 3, "shots_on_target": 2,
                   "fouls_committed": 0, "fouls_suffered": 0, "offsides": 0, "yellow_cards": 0, "red_cards": 0,
                   "own_goals": 0, "saves": 0, "goals_conceded": 0, "shots_faced": 0}
    player_stats = pd.DataFrame([
        {**base_player, "espn_athlete_id": 1, "espn_team_id": 100, "goals": 2},
        {**base_player, "espn_athlete_id": 2, "espn_team_id": 200, "goals": 1},
    ])

    events = pd.DataFrame({
        "espn_event_id": [1, 1, 1],
        "espn_play_id": [11, 12, 13],
        "event_type": ["goal", "goal", "goal"],
        "espn_team_id": [100, 100, 200],
        "espn_athlete_id": [1, 1, 2],
        "secondary_espn_athlete_id": [np.nan, np.nan, np.nan],
        "period": [1, 2, 2],
        "minute": [10, 50, 80],
        "added_time": [0, 0, 0],
    })
    return {
        "matches": matches, "clubs": clubs, "players": players,
        "club_match_stats": club_stats, "player_match_stats": player_stats, "match_events": events,
    }


def test_clean_data_passes(tables):
    validate_tables(tables)
    report = run_checks(tables)
    assert report.errors == []


def test_negative_count_is_rejected(tables):
    tables["club_match_stats"].loc[0, "shots"] = -1
    with pytest.raises(ValueError, match="club_match_stats"):
        validate_tables(tables)


def test_more_shots_on_target_than_shots_is_rejected(tables):
    tables["player_match_stats"].loc[0, "shots_on_target"] = 9
    with pytest.raises(ValueError, match="more shots on target than shots"):
        validate_tables(tables)


def test_impossible_possession_is_rejected(tables):
    tables["club_match_stats"].loc[0, "possession_pct"] = 104.0
    with pytest.raises(ValueError, match="possession_pct"):
        validate_tables(tables)


def test_kickoff_outside_the_season_is_rejected(tables):
    tables["matches"].loc[0, "kickoff_utc"] = pd.Timestamp("2025-01-01", tz="UTC")
    with pytest.raises(ValueError, match="outside the season"):
        validate_tables(tables)


def test_club_playing_itself_is_rejected(tables):
    tables["matches"].loc[0, "away_espn_id"] = 100
    with pytest.raises(ValueError, match="can't play itself"):
        validate_tables(tables)


def test_unknown_stage_is_rejected(tables):
    tables["matches"].loc[0, "stage"] = "super_final"
    with pytest.raises(ValueError, match="stage"):
        validate_tables(tables)


def test_duplicate_match_is_an_error(tables):
    duplicate = tables["matches"].assign(espn_event_id=2)
    tables["matches"] = pd.concat([tables["matches"], duplicate], ignore_index=True)
    report = run_checks(tables)
    assert any("more than once" in error for error in report.errors)


def test_missing_player_is_an_error(tables):
    tables["players"] = tables["players"].iloc[:1]
    report = run_checks(tables)
    assert any("player_match_stats.player" in error for error in report.errors)


def test_same_name_under_two_ids_is_an_error(tables):
    tables["clubs"].loc[1, "name"] = "Home FC"
    report = run_checks(tables)
    assert any("more than one ESPN id" in error for error in report.errors)


def test_goals_that_dont_match_the_score_are_reported(tables):
    # One inconsistent match out of one is over the 2% limit, so it's an error.
    tables["player_match_stats"].loc[0, "goals"] = 1
    report = run_checks(tables)
    assert len(report.inconsistent_matches) == 1
    assert any("don't match the score" in error for error in report.errors)


def test_stat_coverage_spots_an_all_zero_stat(tables):
    tables["club_match_stats"]["interceptions"] = 0.0
    coverage = stat_coverage_by_season(tables["club_match_stats"], tables["matches"])
    row = coverage[coverage["stat"] == "interceptions"].iloc[0]
    assert row["nonzero_share"] == 0
    report = run_checks(tables)
    assert any("'interceptions' is zero" in warning for warning in report.warnings)


def test_missing_stats_become_null_only_in_the_affected_season(tables):
    other_season = tables["matches"].assign(espn_event_id=2, season_year=2023)
    matches = pd.concat([tables["matches"], other_season], ignore_index=True)
    club_stats = pd.concat(
        [tables["club_match_stats"], tables["club_match_stats"].assign(espn_event_id=2)], ignore_index=True
    )
    club_stats.loc[club_stats["espn_event_id"] == 1, "interceptions"] = 0.0

    cleaned = blank_missing_stats(club_stats, matches)
    assert cleaned.loc[cleaned["espn_event_id"] == 1, "interceptions"].isna().all()
    assert (cleaned.loc[cleaned["espn_event_id"] == 2, "interceptions"] == 5.0).all()
    # Stats that are often 0 for real, like red cards, are left alone.
    club_stats["red_cards"] = 0.0
    assert (blank_missing_stats(club_stats, matches)["red_cards"] == 0).all()


def test_a_match_with_zero_passes_has_its_passing_and_defending_blanked(tables):
    club_stats = tables["club_match_stats"].copy()
    club_stats.loc[0, ["passes", "passes_completed", "tackles", "interceptions"]] = 0.0

    cleaned = blank_missing_stats(club_stats, tables["matches"])
    assert cleaned.loc[0, ["passes", "tackles", "interceptions"]].isna().all()
    # Shots were recorded, so they stay.
    assert cleaned.loc[0, "shots"] == 5.0
    # The other team's row is untouched.
    assert cleaned.loc[1, "passes"] == 5.0
