import numpy as np
import pandas as pd
import pytest

from src.analysis.finishing import goals_above_average
from src.analysis.player_metrics import default_min_minutes, per90, poisson_rate_interval
from src.analysis.tactical import PROFILE_FEATURES, describe_cluster, similar_clubs
from src.analysis.tournament_index import DEFAULT_WEIGHTS, index_components, tournament_index, zscore_within_season


class TestPer90:
    def test_basic_rate(self):
        assert per90(3, 270) == pytest.approx(1.0)

    def test_zero_minutes_gives_nan_not_an_error(self):
        assert np.isnan(per90(1, 0))

    def test_works_on_columns(self):
        rates = per90([0, 2, 5], [90, 180, 0])
        assert rates[:2].tolist() == [0.0, 1.0]
        assert np.isnan(rates[2])


class TestPoissonInterval:
    def test_interval_contains_the_rate(self):
        lower, upper = poisson_rate_interval(5, 450)
        assert lower < 1.0 < upper

    def test_zero_goals_has_lower_bound_zero(self):
        lower, upper = poisson_rate_interval(0, 900)
        assert lower == 0
        assert upper > 0

    def test_fewer_minutes_means_a_wider_interval(self):
        short_low, short_high = poisson_rate_interval(1, 90)
        long_low, long_high = poisson_rate_interval(10, 900)
        assert (short_high - short_low) > (long_high - long_low)


class TestDefaultMinMinutes:
    def test_full_season_uses_three_games(self):
        assert default_min_minutes(pd.DataFrame({"minutes": [1200, 90]})) == 270

    def test_early_season_drops_the_threshold(self):
        assert default_min_minutes(pd.DataFrame({"minutes": [90, 45]})) == 45

    def test_empty(self):
        assert default_min_minutes(pd.DataFrame({"minutes": []})) == 0


class TestTournamentIndex:
    @pytest.fixture
    def club_matches(self):
        # Two clubs, two made-up games each, same season.
        return pd.DataFrame({
            "match_id": [1, 1, 2, 2],
            "season_year": [2021] * 4,
            "club_id": [1, 2, 1, 2],
            "kickoff_utc": pd.to_datetime(["2021-10-01", "2021-10-01", "2021-10-08", "2021-10-08"]),
            "stage": ["group_stage"] * 4,
            "points": [3, 0, 1, 1],
            "goals_for": [2, 0, 1, 1],
            "goals_against": [0, 2, 1, 1],
            "shots_on_target": [5, 2, 3, 3],
            "shots_on_target_against": [2, 5, 3, 3],
            "opponent_elo_before": [1500, 1500, 1500, 1500],
            "won_match": [True, False, False, False],
        })

    def test_constant_column_gets_zero_z_scores(self):
        frame = pd.DataFrame({"season_year": [1, 1, 1], "value": [4.0, 4.0, 4.0]})
        assert zscore_within_season(frame, ["value"])["value"].tolist() == [0.0, 0.0, 0.0]

    def test_better_club_ranks_first(self, club_matches):
        components = index_components(club_matches, finished_seasons=set())
        result = tournament_index(components)
        assert result.iloc[0]["club_id"] == 1
        assert result.iloc[0]["tpi"] > 0 > result.iloc[1]["tpi"]

    def test_progression_is_missing_for_unfinished_seasons(self, club_matches):
        components = index_components(club_matches, finished_seasons=set())
        assert components["progression"].isna().all()

    def test_missing_component_weight_is_shared_out(self, club_matches):
        components = index_components(club_matches, finished_seasons=set())
        result = tournament_index(components)
        # With progression missing, the index is the weighted mean of the other z-scores.
        others = {name: weight for name, weight in DEFAULT_WEIGHTS.items() if name != "progression"}
        row = result.iloc[0]
        expected = sum(row[f"{name}_z"] * weight for name, weight in others.items()) / sum(others.values())
        assert row["tpi"] == pytest.approx(expected)


def test_goals_above_average_sums_to_zero_over_a_season():
    players = pd.DataFrame({
        "season_year": [2020, 2020, 2020],
        "non_penalty_goals": [6, 1, 3],
        "non_penalty_shots": [30, 10, 20],
        "non_penalty_shots_on_target": [12, 4, 8],
    })
    result = goals_above_average(players)
    # Everyone is compared to the average of the same group, so the differences cancel out.
    assert result["goals_above_average"].sum() == pytest.approx(0)
    assert result.loc[0, "goals_above_average"] > 0


def test_goals_above_average_handles_players_without_shots():
    players = pd.DataFrame({
        "season_year": [2020, 2020],
        "non_penalty_goals": [2, 0],
        "non_penalty_shots": [10, 0],
        "non_penalty_shots_on_target": [5, 0],
    })
    result = goals_above_average(players)
    assert np.isnan(result.loc[1, "np_conversion"])
    assert result.loc[1, "goals_above_average"] == 0


class TestTactical:
    def test_describes_high_and_low_features(self):
        centre = pd.Series(0.0, index=list(PROFILE_FEATURES))
        centre["possession_pct"] = 1.2
        centre["clearances"] = -0.9
        description = describe_cluster(centre)
        assert description.startswith("Higher possession %")
        assert "lower clearances / match" in description

    def test_average_cluster(self):
        centre = pd.Series(0.1, index=list(PROFILE_FEATURES))
        assert describe_cluster(centre) == "Close to average on every measure"

    def test_similar_clubs_excludes_itself_and_finds_the_nearest(self):
        rng = np.random.default_rng(0)
        profiles = pd.DataFrame(rng.normal(size=(5, len(PROFILE_FEATURES))), columns=list(PROFILE_FEATURES))
        profiles["season_year"] = 2020
        profiles["club_id"] = [1, 2, 3, 4, 5]
        # Make club 4 an almost exact copy of club 1.
        profiles.loc[3, list(PROFILE_FEATURES)] = profiles.loc[0, list(PROFILE_FEATURES)] + 0.01

        result = similar_clubs(profiles, 2020, 1, n=2)
        assert 1 not in result["club_id"].tolist()
        assert result.iloc[0]["club_id"] == 4

    def test_similar_clubs_unknown_club_raises(self):
        profiles = pd.DataFrame({name: [0.0, 1.0] for name in PROFILE_FEATURES})
        profiles["season_year"] = 2020
        profiles["club_id"] = [1, 2]
        with pytest.raises(KeyError):
            similar_clubs(profiles, 2020, 99)
