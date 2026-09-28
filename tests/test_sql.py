"""
SQL tests against a real PostgreSQL database.

They build the real schema and views in a separate test database, insert a
tiny made-up season, and check the views and named queries against numbers
worked out by hand. Skipped if no database is reachable.

Set TEST_DATABASE_URL to point somewhere else. By default it uses the normal
connection settings with "_test" added to the database name.
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from src.config import SQL_DIR, database_url
from src.database.queries import load_queries

# Made-up season: three clubs, three group games, a final won on penalties and one unplayed game.
#   m1  Alpha 2-0 Beta         (Alpha: one penalty, one open-play goal)
#   m2  Beta 1-1 Gamma
#   m3  Gamma 1-3 Alpha        (Gamma scored first, Alpha came back)
#   m4  Alpha 1-1 Gamma, final, extra time, Alpha win 4-2 on penalties
#   m5  Alpha v Gamma, not played yet
FIXTURE_SQL = """
INSERT INTO competitions (competition_id, name, espn_slug) VALUES (1, 'Test Cup', 'test.cup');
INSERT INTO seasons (season_id, competition_id, start_year, label, format) VALUES (1, 1, 2022, '2022-23', 'group_stage');
INSERT INTO clubs (club_id, espn_team_id, name, short_name) VALUES
    (1, 101, 'Alpha FC', 'Alpha'), (2, 102, 'Beta FC', 'Beta'), (3, 103, 'Gamma FC', 'Gamma');
INSERT INTO players (player_id, espn_athlete_id, full_name) VALUES
    (1, 1001, 'Alpha Striker'), (2, 1002, 'Beta Sub'), (3, 1003, 'Gamma Forward'),
    (4, 1004, 'Beta Forward'), (5, 1005, 'Alpha Winger');

INSERT INTO matches (match_id, espn_event_id, season_id, stage, group_name, kickoff_utc, status,
                     home_club_id, away_club_id, home_goals, away_goals, home_goals_90, away_goals_90,
                     went_to_extra_time, home_shootout_goals, away_shootout_goals, winner_club_id, is_neutral_venue)
VALUES
    (1, 9001, 1, 'group_stage', 'A', '2022-09-10 19:00+00', 'finished', 1, 2, 2, 0, 2, 0, FALSE, NULL, NULL, 1, FALSE),
    (2, 9002, 1, 'group_stage', 'A', '2022-09-17 19:00+00', 'finished', 2, 3, 1, 1, 1, 1, FALSE, NULL, NULL, NULL, FALSE),
    (3, 9003, 1, 'group_stage', 'A', '2022-09-24 19:00+00', 'finished', 3, 1, 1, 3, 1, 3, FALSE, NULL, NULL, 1, FALSE),
    (4, 9004, 1, 'final', NULL, '2023-05-30 19:00+00', 'finished', 1, 3, 1, 1, 1, 1, TRUE, 4, 2, 1, TRUE),
    (5, 9005, 1, 'group_stage', 'A', '2022-10-01 19:00+00', 'scheduled', 1, 3, NULL, NULL, NULL, NULL, FALSE, NULL, NULL, NULL, FALSE);

INSERT INTO club_match_stats (match_id, club_id, possession_pct, shots, shots_on_target, passes, passes_completed) VALUES
    (1, 1, 60, 12, 6, 500, 450), (1, 2, 40, 5, 1, 300, 240),
    (2, 2, 50, 8, 3, 400, 340), (2, 3, 50, 9, 4, 400, 330),
    (3, 3, 45, 7, 2, 350, 290), (3, 1, 55, 14, 7, 450, 400),
    (4, 1, 52, 15, 5, 600, 540), (4, 3, 48, 11, 4, 560, 490);

INSERT INTO player_match_stats (match_id, player_id, club_id, position_group, is_starter, minute_on, minute_off,
                                minutes_played, goals, shots, shots_on_target) VALUES
    (1, 1, 1, 'FWD', TRUE, 0, 90, 90, 2, 4, 3),
    (3, 1, 1, 'FWD', TRUE, 0, 90, 90, 1, 2, 1),
    (1, 2, 2, 'MID', FALSE, 90, 90, 0, 0, 0, 0),
    (2, 3, 3, 'FWD', TRUE, 0, 90, 90, 1, 3, 2),
    (3, 3, 3, 'FWD', TRUE, 0, 90, 90, 1, 2, 1);

INSERT INTO match_events (match_id, espn_play_id, event_type, club_id, player_id, period, minute) VALUES
    (1, 1, 'penalty_goal', 1, 1, 1, 20),
    (1, 2, 'goal', 1, 1, 2, 60),
    (2, 3, 'goal', 2, 4, 1, 10),
    (2, 4, 'goal', 3, 3, 2, 80),
    (3, 5, 'goal', 3, 3, 1, 10),
    (3, 6, 'goal', 1, 1, 1, 30),
    (3, 7, 'own_goal', 1, 3, 2, 50),
    (3, 8, 'goal', 1, 5, 2, 70),
    (4, 9, 'goal', 1, 5, 1, 30),
    (4, 10, 'goal', 3, 3, 2, 60);

INSERT INTO club_elo (match_id, club_id, elo_before, elo_after) VALUES
    (1, 1, 1500, 1510), (1, 2, 1500, 1490),
    (2, 2, 1490, 1489), (2, 3, 1500, 1501),
    (3, 3, 1501, 1490), (3, 1, 1510, 1521),
    (4, 1, 1521, 1521), (4, 3, 1490, 1490),
    (5, 1, 1521, NULL), (5, 3, 1490, NULL);
"""


def sql_test_url() -> str:
    if os.getenv("TEST_DATABASE_URL"):
        return os.environ["TEST_DATABASE_URL"]
    url = make_url(database_url())
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


@pytest.fixture(scope="module")
def engine():
    url = make_url(sql_test_url())
    admin_url = url.set(database="postgres")
    try:
        admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database}
            ).scalar()
            if not exists:
                connection.execute(text(f'CREATE DATABASE "{url.database}"'))
        admin.dispose()
    except OperationalError:
        pytest.skip("No PostgreSQL database available for SQL tests")

    engine = create_engine(url)
    with engine.begin() as connection:
        connection.exec_driver_sql((SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
        connection.exec_driver_sql((SQL_DIR / "views.sql").read_text(encoding="utf-8"))
        connection.exec_driver_sql(FIXTURE_SQL)
    yield engine
    engine.dispose()


def fetch(engine, sql, **params):
    with engine.connect() as connection:
        return [dict(row._mapping) for row in connection.execute(text(sql), params)]


def run_named(engine, name, **params):
    return fetch(engine, load_queries()[name], **params)


class TestViews:
    def test_club_matches_has_two_rows_per_finished_match(self, engine):
        rows = fetch(engine, "SELECT match_id, COUNT(*) AS n FROM v_club_matches GROUP BY match_id ORDER BY match_id")
        assert rows == [{"match_id": i, "n": 2} for i in (1, 2, 3, 4)]

    def test_club_matches_joins_the_opponents_shots(self, engine):
        row = fetch(engine, "SELECT shots, shots_against FROM v_club_matches WHERE match_id = 1 AND club_id = 1")[0]
        assert (row["shots"], row["shots_against"]) == (12, 5)

    def test_season_totals(self, engine):
        rows = {r["club_name"]: r for r in fetch(engine, "SELECT * FROM v_club_season_stats")}
        alpha = rows["Alpha FC"]
        assert (alpha["matches"], alpha["points"], alpha["goals_for"], alpha["goals_against"]) == (3, 7, 6, 2)
        assert alpha["clean_sheets"] == 1
        assert alpha["penalty_goals"] == 1
        assert alpha["won_title"] is True
        assert rows["Gamma FC"]["won_title"] is False

    def test_standings_break_ties_on_goals_scored(self, engine):
        rows = fetch(engine, "SELECT club_id, points, position FROM v_group_standings ORDER BY position")
        # Beta and Gamma both have 1 point and -2 goal difference; Gamma scored more.
        assert [(r["club_id"], r["points"], r["position"]) for r in rows] == [(1, 6, 1), (3, 1, 2), (2, 1, 3)]

    def test_player_totals_are_not_duplicated_by_the_penalty_join(self, engine):
        row = fetch(engine, "SELECT * FROM v_player_season_stats WHERE player_id = 1")[0]
        assert (row["appearances"], row["minutes"], row["goals"]) == (2, 180, 3)
        assert row["penalty_goals"] == 1
        assert (row["non_penalty_goals"], row["non_penalty_shots"], row["non_penalty_shots_on_target"]) == (2, 5, 3)
        assert float(row["goals_per90"]) == pytest.approx(1.5)

    def test_zero_minutes_gives_null_rates(self, engine):
        row = fetch(engine, "SELECT minutes, goals_per90 FROM v_player_season_stats WHERE player_id = 2")[0]
        assert row["minutes"] == 0
        assert row["goals_per90"] is None


class TestNamedQueries:
    def test_home_advantage_counts_each_match_once(self, engine):
        rows = run_named(engine, "home_advantage_by_season")
        # Three non-neutral finished games: one home win, one draw, one away win.
        assert rows[0]["matches"] == 3
        assert float(rows[0]["home_win_rate"]) == pytest.approx(1 / 3, abs=0.001)

    def test_recent_form_is_newest_first(self, engine):
        rows = {r["club_name"]: r for r in run_named(engine, "recent_form", season_year=2022)}
        assert rows["Alpha FC"]["last_five"] == "DWW"

    def test_comeback_is_found(self, engine):
        rows = run_named(engine, "comeback_wins")
        assert len(rows) == 1
        assert (rows[0]["winner"], rows[0]["final_score"], rows[0]["biggest_deficit"]) == ("Alpha FC", "1-3", 1)

    def test_goals_by_period_adds_up(self, engine):
        rows = run_named(engine, "goals_by_match_period", from_season=2022, to_season=2022)
        assert sum(r["goals"] for r in rows) == 10
        assert sum(float(r["share_pct"]) for r in rows) == pytest.approx(100, abs=0.5)

    def test_finishing_vs_average_sums_to_zero(self, engine):
        rows = run_named(engine, "finishing_vs_average", season_year=2022, min_shots=0)
        assert sum(float(r["goals_above_average"]) for r in rows) == pytest.approx(0, abs=0.05)

    def test_every_named_query_runs(self, engine):
        params = {
            "season_year": 2022, "limit": 10, "min_minutes": 0, "min_shots": 0, "player_ids": [1, 3],
            "club_id": 1, "from_season": 2012, "to_season": 2030, "current_season": 2030,
        }
        for sql in load_queries().values():
            used = {key: value for key, value in params.items() if f":{key}" in sql}
            fetch(engine, sql, **used)
