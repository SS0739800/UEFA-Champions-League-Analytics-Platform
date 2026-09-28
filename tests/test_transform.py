import pandas as pd
import pytest

from src.etl.transform import (
    drop_repeated_roster_rows,
    fill_sub_positions,
    goals_after_90,
    is_neutral_venue,
    normalize_club_name,
    normalize_stage,
    parse_clock,
    parse_event,
    parse_group_name,
    parse_key_events,
    player_minutes,
    position_group,
)
from tests.conftest import key_event, make_event, play, roster_player


class TestStages:
    def test_spelling_variants_map_to_one_name(self):
        assert normalize_stage("quarter-finals") == normalize_stage("quarterfinals") == "quarter_final"

    def test_qualifying_rounds_are_dropped(self):
        assert normalize_stage("qualifying-third-round") is None
        assert normalize_stage("playoff-round") is None

    def test_unknown_slug_raises(self):
        with pytest.raises(ValueError, match="Unknown ESPN stage slug"):
            normalize_stage("super-final")


class TestClock:
    @pytest.mark.parametrize("text, expected", [("73'", (73, 0)), ("45'+2'", (45, 2)), ("90'+11'", (90, 11))])
    def test_parses_minutes_and_added_time(self, text, expected):
        assert parse_clock(text) == expected

    def test_empty_clock_raises(self):
        with pytest.raises(ValueError):
            parse_clock("")


class TestNames:
    def test_decomposed_accents_match_composed_ones(self):
        decomposed = "Atlético Madrid"
        assert normalize_club_name(decomposed) == "Atlético Madrid"

    def test_known_fixes_and_whitespace(self):
        assert normalize_club_name("  Internazionale ") == "Inter"
        assert normalize_club_name("Bayern  Munich") == "Bayern Munich"


class TestPositions:
    def test_groups(self):
        assert position_group("G") == "GK"
        assert position_group("CD-L") == "DEF"
        assert position_group("AM-R") == "MID"
        assert position_group("RCF") == "FWD"

    def test_substitutes_have_no_group_yet(self):
        assert position_group("SUB") is None

    def test_unknown_code_is_unk(self):
        assert position_group("XYZ") == "UNK"

    def test_subs_borrow_their_usual_starting_group(self):
        stats = pd.DataFrame({
            "espn_athlete_id": [1, 1, 1, 2],
            "position_group": ["FWD", "FWD", None, None],
            "is_starter": [True, True, False, False],
        })
        filled = fill_sub_positions(stats)
        assert filled["position_group"].tolist() == ["FWD", "FWD", "FWD", "UNK"]


class TestGroups:
    @pytest.mark.parametrize("competition", [
        {"group": {"abbreviation": "C"}},
        {"group": {"abbreviation": "UEFA CHAMPIONS LEAGUE - GROUP C"}},
        {"altGameNote": "UEFA Champions League, Group C"},
        {"altGameNote": "UEFA Champions League, UEFA CHAMPIONS LEAGUE - GROUP C"},
    ])
    def test_finds_the_letter_wherever_espn_put_it(self, competition):
        assert parse_group_name(competition) == "C"

    def test_no_group(self):
        assert parse_group_name({"altGameNote": "UEFA Champions League, Round of 16"}) is None


class TestPlayerMinutes:
    def test_starter_plays_full_match(self):
        assert player_minutes(roster_player(1, "A"), 90) == (0, 90)

    def test_starter_subbed_off(self):
        player = roster_player(1, "A", subbed_out=True, plays=[play("63'", substitution=True)])
        assert player_minutes(player, 90) == (0, 63)

    def test_sub_comes_on(self):
        player = roster_player(1, "A", position="SUB", starter=False, subbed_in=True,
                               plays=[play("70'", substitution=True)])
        assert player_minutes(player, 90) == (70, 90)

    def test_sub_comes_on_and_goes_off(self):
        player = roster_player(1, "A", starter=False, subbed_in=True, subbed_out=True,
                               plays=[play("80'", substitution=True), play("46'", substitution=True)])
        assert player_minutes(player, 90) == (46, 80)

    def test_red_card_ends_the_game_early(self):
        player = roster_player(1, "A", plays=[play("55'"), play("79'", red_card=True)])
        assert player_minutes(player, 90) == (0, 79)

    def test_extra_time_counts(self):
        assert player_minutes(roster_player(1, "A"), 120) == (0, 120)

    def test_sub_in_added_time_gets_zero_minutes(self):
        player = roster_player(1, "A", starter=False, subbed_in=True, plays=[play("90'+3'", substitution=True)])
        assert player_minutes(player, 90) == (90, 90)


class TestParseEvent:
    def test_home_and_away_come_from_home_away_not_list_order(self):
        row = parse_event(make_event(home_score="3", away_score="1"))
        assert row["home_espn_id"] == 100
        assert row["home_goals"] == 3
        assert row["winner_espn_id"] == 100

    def test_scheduled_match_has_no_score(self):
        row = parse_event(make_event(completed=False, status_name="STATUS_SCHEDULED", home_score="0", away_score="0"))
        assert row["status"] == "scheduled"
        assert row["home_goals"] is None
        assert row["winner_espn_id"] is None

    def test_penalty_shootout(self):
        event = make_event(
            slug="final", home_score="1", away_score="1", status_name="STATUS_FINAL_PEN", period=5,
            home_extra={"shootoutScore": 5, "winner": True}, away_extra={"shootoutScore": 3},
        )
        row = parse_event(event)
        assert row["went_to_extra_time"]
        assert (row["home_shootout_goals"], row["away_shootout_goals"]) == (5, 3)
        assert row["winner_espn_id"] == 100
        assert row["is_neutral_venue"]

    def test_zero_attendance_is_unknown(self):
        row = parse_event(make_event(extra_competition={"attendance": 0}))
        assert row["attendance"] is None


def test_neutral_venues():
    assert is_neutral_venue(2019, "semi_final", None)
    assert not is_neutral_venue(2019, "round_of_16", None)
    assert is_neutral_venue(2022, "final", None)
    assert is_neutral_venue(2022, "group_stage", True)


class TestKeyEvents:
    def test_shootout_kicks_and_markers_are_skipped(self):
        summary = {"keyEvents": [
            key_event(1, "kickoff", None, "", 1),
            key_event(2, "goal", 100, "12'", 1, athletes=[7, 8]),
            key_event(3, "penalty---scored", 200, "121'", 5, athletes=[9], shootout=True),
        ]}
        rows = parse_key_events(summary, espn_event_id=1)
        assert len(rows) == 1
        assert rows[0]["event_type"] == "goal"
        assert rows[0]["espn_athlete_id"] == 7
        assert rows[0]["secondary_espn_athlete_id"] == 8

    def test_saved_and_missed_penalties_stay_separate(self):
        summary = {"keyEvents": [
            key_event(1, "penalty---saved", 100, "30'", 1, athletes=[7]),
            key_event(2, "penalty---hit-woodwork", 100, "60'", 2, athletes=[7]),
        ]}
        types = [row["event_type"] for row in parse_key_events(summary, espn_event_id=1)]
        assert types == ["penalty_saved", "penalty_missed"]


def test_goals_after_90_ignores_extra_time():
    matches = pd.DataFrame({
        "espn_event_id": [1], "status": ["finished"], "home_espn_id": [100], "away_espn_id": [200],
    })
    events = pd.DataFrame({
        "espn_event_id": [1, 1, 1, 1],
        "espn_team_id": [100, 200, 100, 200],
        "event_type": ["goal", "own_goal", "goal", "yellow_card"],
        "period": [1, 2, 3, 2],
    })
    result = goals_after_90(events, matches)
    # The own goal is credited to club 200, the extra-time goal doesn't count.
    assert result.loc[0, "home_goals_90"] == 1
    assert result.loc[0, "away_goals_90"] == 1


def test_exact_duplicate_roster_rows_are_dropped_but_conflicts_are_kept():
    rows = pd.DataFrame({"espn_event_id": [1, 1, 1, 1], "espn_athlete_id": [5, 5, 6, 6], "saves": [3, 3, 1, 2]})
    result = drop_repeated_roster_rows(rows)
    assert result["espn_athlete_id"].tolist() == [5, 6, 6]
