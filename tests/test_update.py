"""
Tests for the incremental update (python -m src.etl.run --update) and the bits
it depends on. The database tests use the same throwaway _test database as
test_sql.py and are skipped without one. All clubs, players and numbers are made up.
"""

from datetime import date

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import text

from src.config import SQL_DIR, database_url, season_for
from src.etl import extract
from src.etl.load import finished_event_ids, load_all, load_update, record_run
from src.etl.transform import (
    CLUB_STAT_COLUMNS,
    CLUB_STATS_FRAME,
    EVENTS_FRAME,
    PLAYER_STAT_COLUMNS,
    PLAYER_STATS_FRAME,
    fill_sub_positions,
    transform,
)
from src.validation.schemas import validate_tables
from tests.conftest import make_event

# --- Building transform-shaped tables by hand -------------------------------------------

CLUBS = pd.DataFrame({"espn_team_id": [101, 102], "name": ["Alpha FC", "Beta FC"],
                      "short_name": ["Alpha", "Beta"], "abbreviation": ["ALP", "BET"]})
PLAYERS = pd.DataFrame({"espn_athlete_id": [1001, 1002], "full_name": ["Alpha Striker", "Beta Keeper"]})


def match_row(event_id, status, home_goals=None, away_goals=None, day="2026-09-15"):
    finished = status == "finished"
    return {
        "espn_event_id": event_id, "season_year": 2026, "stage": "league_phase", "group_name": None,
        "leg": np.nan, "kickoff_utc": pd.Timestamp(f"{day} 19:00", tz="UTC"), "status": status,
        "home_espn_id": 101, "away_espn_id": 102,
        "home_goals": float(home_goals) if finished else np.nan,
        "away_goals": float(away_goals) if finished else np.nan,
        "went_to_extra_time": False, "home_shootout_goals": None, "away_shootout_goals": None,
        "winner_espn_id": 101.0 if finished and home_goals > away_goals else np.nan,
        "is_neutral_venue": False, "venue": "Test Stadium", "attendance": np.nan,
        "home_goals_90": float(home_goals) if finished else np.nan,
        "away_goals_90": float(away_goals) if finished else np.nan,
    }


def detail_rows(event_id, home_goals):
    """Team stats, player stats and events for one finished made-up match."""
    club_stats = pd.DataFrame([
        {"espn_event_id": event_id, "espn_team_id": team, **dict.fromkeys(CLUB_STAT_COLUMNS.values(), 5.0),
         "possession_pct": 50.0}
        for team in (101, 102)
    ])[CLUB_STATS_FRAME]
    player = {"espn_event_id": event_id, "espn_athlete_id": 1001, "espn_team_id": 101, "position": "F",
              "position_group": "FWD", "is_starter": True, "minute_on": 0, "minute_off": 90, "minutes_played": 90,
              **dict.fromkeys(PLAYER_STAT_COLUMNS.values(), 0)}
    player.update(goals=home_goals, shots=home_goals, shots_on_target=home_goals)
    player_stats = pd.DataFrame([player])[[c for c in PLAYER_STATS_FRAME if c != "player_name"]]
    events = pd.DataFrame([
        {"espn_event_id": event_id, "espn_play_id": event_id * 10 + i, "event_type": "goal", "espn_team_id": 101,
         "espn_athlete_id": 1001, "secondary_espn_athlete_id": np.nan, "period": 1, "minute": 10 + i, "added_time": 0}
        for i in range(home_goals)
    ], columns=[c for c in EVENTS_FRAME if c not in ("player_name", "secondary_player_name")])
    return club_stats, player_stats, events


def tables_for(match_rows, finished_goals):
    """finished_goals maps event id -> home goals for the matches that are finished."""
    details = [detail_rows(event_id, goals) for event_id, goals in finished_goals.items()]
    empty = detail_rows(0, 0)
    matches = pd.DataFrame(match_rows)
    numeric = ["leg", "home_goals", "away_goals", "home_shootout_goals", "away_shootout_goals",
               "winner_espn_id", "attendance", "home_goals_90", "away_goals_90"]
    matches[numeric] = matches[numeric].astype(float)
    return {
        "matches": matches,
        "clubs": CLUBS.copy(),
        "players": PLAYERS.copy(),
        "club_match_stats": pd.concat([d[0] for d in details], ignore_index=True) if details else empty[0].iloc[:0],
        "player_match_stats": pd.concat([d[1] for d in details], ignore_index=True) if details else empty[1].iloc[:0],
        "match_events": pd.concat([d[2] for d in details], ignore_index=True) if details else empty[2].iloc[:0],
    }


@pytest.fixture
def loaded(test_engine):
    """A database with one finished match (1) and one still to be played (2)."""
    initial = tables_for([match_row(1, "finished", 2, 0), match_row(2, "scheduled", day="2026-09-30")], {1: 2})
    load_all(test_engine, initial)
    return test_engine


def count(db, sql):
    with db.connect() as connection:
        return connection.execute(text(sql)).scalar()


# --- Database tests ---------------------------------------------------------------------

def test_update_fills_in_a_newly_finished_match(loaded):
    update = tables_for([match_row(2, "finished", 3, 1, day="2026-09-30")], {2: 3})
    assert load_update(loaded, update) == 1

    assert count(loaded, "SELECT COUNT(*) FROM matches") == 2
    assert count(loaded, "SELECT home_goals FROM matches WHERE espn_event_id = 2") == 3
    assert count(loaded, "SELECT COUNT(*) FROM club_match_stats") == 4
    assert count(loaded, "SELECT COUNT(*) FROM match_events") == 2 + 3
    assert finished_event_ids(loaded) == {1, 2}


def test_running_the_same_update_twice_changes_nothing(loaded):
    update = tables_for([match_row(2, "finished", 3, 1, day="2026-09-30")], {2: 3})
    load_update(loaded, update)
    load_update(loaded, update)
    assert count(loaded, "SELECT COUNT(*) FROM player_match_stats") == 2
    assert count(loaded, "SELECT COUNT(*) FROM match_events") == 5


def test_update_leaves_older_matches_alone(loaded):
    before = count(loaded, "SELECT COUNT(*) FROM match_events WHERE match_id = "
                           "(SELECT match_id FROM matches WHERE espn_event_id = 1)")
    load_update(loaded, tables_for([match_row(2, "finished", 1, 0, day="2026-09-30")], {2: 1}))
    after = count(loaded, "SELECT COUNT(*) FROM match_events WHERE match_id = "
                          "(SELECT match_id FROM matches WHERE espn_event_id = 1)")
    assert before == after == 2


def test_update_renames_a_club_without_changing_its_id(loaded):
    old_id = count(loaded, "SELECT club_id FROM clubs WHERE espn_team_id = 101")
    update = tables_for([match_row(2, "scheduled", day="2026-10-01")], {})
    update["clubs"].loc[0, "name"] = "Alpha City"
    load_update(loaded, update)
    assert count(loaded, "SELECT club_id FROM clubs WHERE name = 'Alpha City'") == old_id


def test_rescheduled_fixture_gets_its_new_date(loaded):
    load_update(loaded, tables_for([match_row(2, "scheduled", day="2026-10-07")], {}))
    kickoff = count(loaded, "SELECT kickoff_utc::date FROM matches WHERE espn_event_id = 2")
    assert kickoff == date(2026, 10, 7)


def test_update_on_an_empty_database_explains_what_to_do(test_engine):
    with test_engine.begin() as connection:
        connection.exec_driver_sql((SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
    with pytest.raises(RuntimeError, match="full load first"):
        load_update(test_engine, tables_for([match_row(2, "scheduled")], {}))


def test_run_history_survives_a_full_rebuild(loaded):
    record_run(loaded, "update", "succeeded", finished_matches=3)
    load_all(loaded, tables_for([match_row(1, "finished", 2, 0)], {1: 2}))
    assert count(loaded, "SELECT COUNT(*) FROM pipeline_runs WHERE finished_matches = 3") >= 1


# --- No database needed ------------------------------------------------------------------

def test_transform_with_only_scheduled_matches_gives_empty_but_valid_tables(tmp_path):
    scheduled = make_event(event_id="5", slug="league-phase", completed=False, status_name="STATUS_SCHEDULED",
                           home_score="0", away_score="0")
    tables = transform([scheduled], tmp_path)
    assert len(tables["matches"]) == 1
    assert tables["player_match_stats"].empty
    assert "minutes_played" in tables["player_match_stats"].columns
    validate_tables(tables)


def test_subs_can_use_positions_from_earlier_seasons():
    new_rows = pd.DataFrame({"espn_athlete_id": [7], "position_group": [None], "is_starter": [False]})
    known = pd.Series({7: "DEF"})
    assert fill_sub_positions(new_rows, known).loc[0, "position_group"] == "DEF"


@pytest.mark.parametrize("day, season", [
    (date(2026, 9, 29), 2026), (date(2027, 5, 29), 2026), (date(2027, 7, 1), 2027), (date(2027, 6, 30), 2026),
])
def test_season_comes_from_the_date(day, season):
    assert season_for(day) == season


def test_hosted_database_urls_use_psycopg(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@pooler.example.com:5432/postgres?sslmode=require")
    assert database_url() == "postgresql+psycopg://user:pw@pooler.example.com:5432/postgres?sslmode=require"
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pw@host/db")
    assert database_url().startswith("postgresql+psycopg://")


def test_update_extract_only_returns_new_recent_fixtures(monkeypatch):
    events = [
        make_event(event_id="1", season_year=2026, slug="league-phase"),                     # already loaded
        make_event(event_id="2", season_year=2026, slug="league-phase"),                     # newly finished
        make_event(event_id="3", season_year=2026, slug="league-phase", completed=False,
                   status_name="STATUS_SCHEDULED", home_score="0", away_score="0"),          # to come
        make_event(event_id="4", season_year=2020, slug="group-stage"),                      # too old
        make_event(event_id="5", season_year=2026, slug="qualifying-third-round"),           # qualifier
    ]
    downloaded = []
    monkeypatch.setattr(extract, "CURRENT_SEASON", 2026)
    monkeypatch.setattr(extract, "make_session", lambda: None)
    monkeypatch.setattr(extract, "fetch_scoreboards", lambda session, refresh_years, years: events)
    monkeypatch.setattr(extract, "fetch_summaries", lambda session, ids: downloaded.extend(ids))

    pending = extract.run_extract_update(already_finished={1})
    assert sorted(event["id"] for event in pending) == ["2", "3"]
    assert downloaded == ["2"]
