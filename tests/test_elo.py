import pandas as pd
import pytest

from src.features.elo import (
    BASE_RATING,
    NEW_CLUB_RATING,
    calculate_elo,
    expected_score,
    margin_multiplier,
)


def test_expected_score_is_symmetric():
    assert expected_score(0) == pytest.approx(0.5)
    assert expected_score(100) + expected_score(-100) == pytest.approx(1.0)


def test_bigger_wins_move_ratings_more():
    assert margin_multiplier(1) == 1.0
    assert margin_multiplier(-2) == 1.5
    assert margin_multiplier(4) > margin_multiplier(3)


def test_first_match_uses_new_club_rating(simple_matches):
    elo = calculate_elo(simple_matches)
    first = elo[elo["match_id"] == 1]
    assert (first["elo_before"] == NEW_CLUB_RATING).all()


def test_winner_gains_what_loser_loses(simple_matches):
    elo = calculate_elo(simple_matches).set_index(["match_id", "club_id"])
    home_change = elo.loc[(1, 10), "elo_after"] - elo.loc[(1, 10), "elo_before"]
    away_change = elo.loc[(1, 20), "elo_after"] - elo.loc[(1, 20), "elo_before"]
    assert home_change > 0
    assert home_change == pytest.approx(-away_change)


def test_ratings_carry_into_the_next_match(simple_matches):
    elo = calculate_elo(simple_matches).set_index(["match_id", "club_id"])
    assert elo.loc[(3, 10), "elo_before"] == pytest.approx(elo.loc[(1, 10), "elo_after"])


def test_scheduled_match_gets_current_rating_but_no_result(simple_matches):
    elo = calculate_elo(simple_matches).set_index(["match_id", "club_id"])
    assert pd.isna(elo.loc[(4, 30), "elo_after"])
    assert elo.loc[(4, 30), "elo_before"] == pytest.approx(elo.loc[(3, 30), "elo_after"])


def test_home_draw_between_equal_clubs_costs_the_home_side(simple_matches):
    # Club 20 (home) and 30 have different histories by match 2, so build a clean case.
    matches = simple_matches.iloc[[1]].assign(home_club_id=1, away_club_id=2)
    elo = calculate_elo(matches).set_index("club_id")
    assert elo.loc[1, "elo_after"] < elo.loc[1, "elo_before"]


def test_neutral_venue_has_no_home_advantage(simple_matches):
    matches = simple_matches.iloc[[1]].assign(home_club_id=1, away_club_id=2, is_neutral_venue=True)
    elo = calculate_elo(matches).set_index("club_id")
    # A draw between equal clubs at a neutral ground changes nothing.
    assert elo.loc[1, "elo_after"] == pytest.approx(elo.loc[1, "elo_before"])


def test_new_season_pulls_ratings_back_to_average(simple_matches):
    next_season = simple_matches.iloc[[0]].assign(
        match_id=99, season_year=2021, kickoff_utc=pd.Timestamp("2021-10-01", tz="UTC")
    )
    matches = pd.concat([simple_matches.iloc[[0]], next_season])
    elo = calculate_elo(matches, season_regression=0.5).set_index(["match_id", "club_id"])

    after_first = elo.loc[(1, 10), "elo_after"]
    expected_start = after_first + 0.5 * (BASE_RATING - after_first)
    assert elo.loc[(99, 10), "elo_before"] == pytest.approx(expected_start)
