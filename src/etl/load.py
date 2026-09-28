"""
Load the transformed tables into PostgreSQL.

The whole load runs in one transaction: the schema is dropped and rebuilt, then
every table is inserted. If anything fails, the old database stays as it was.
"""

import logging

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from src.config import SQL_DIR, season_label

log = logging.getLogger(__name__)

COMPETITION_NAME = "UEFA Champions League"
COMPETITION_SLUG = "uefa.champions"


def run_sql_file(connection: Connection, filename: str) -> None:
    connection.exec_driver_sql((SQL_DIR / filename).read_text(encoding="utf-8"))


def insert(connection: Connection, table: str, frame: pd.DataFrame) -> None:
    # pandas writes NaN as NULL, which is what we want for missing stats.
    frame.to_sql(table, connection, if_exists="append", index=False, method="multi", chunksize=2000)
    log.info("Loaded %s rows into %s", len(frame), table)


def id_map(connection: Connection, table: str, key: str, source_key: str) -> dict:
    rows = connection.execute(text(f"SELECT {key}, {source_key} FROM {table}")).all()
    return {source_id: our_id for our_id, source_id in rows}


def load_all(engine: Engine, tables: dict[str, pd.DataFrame]) -> None:
    """Rebuild the database from the transformed tables."""
    matches = tables["matches"]

    with engine.begin() as connection:
        run_sql_file(connection, "schema.sql")

        competition_id = connection.execute(
            text("INSERT INTO competitions (name, espn_slug) VALUES (:name, :slug) RETURNING competition_id"),
            {"name": COMPETITION_NAME, "slug": COMPETITION_SLUG},
        ).scalar_one()

        season_years = sorted(matches["season_year"].unique())
        seasons = pd.DataFrame({
            "competition_id": competition_id,
            "start_year": season_years,
            "label": [season_label(year) for year in season_years],
            # The 36-team league phase replaced groups from 2024-25.
            "format": ["league_phase" if year >= 2024 else "group_stage" for year in season_years],
        })
        insert(connection, "seasons", seasons)
        season_ids = id_map(connection, "seasons", "season_id", "start_year")

        insert(connection, "clubs", tables["clubs"])
        club_ids = id_map(connection, "clubs", "club_id", "espn_team_id")

        insert(connection, "players", tables["players"])
        player_ids = id_map(connection, "players", "player_id", "espn_athlete_id")

        match_rows = matches.assign(
            season_id=matches["season_year"].map(season_ids),
            home_club_id=matches["home_espn_id"].map(club_ids),
            away_club_id=matches["away_espn_id"].map(club_ids),
            winner_club_id=matches["winner_espn_id"].map(club_ids),
        ).drop(columns=["season_year", "home_espn_id", "away_espn_id", "winner_espn_id"])
        insert(connection, "matches", match_rows)
        match_ids = id_map(connection, "matches", "match_id", "espn_event_id")

        club_stats = tables["club_match_stats"].assign(
            match_id=lambda df: df["espn_event_id"].map(match_ids),
            club_id=lambda df: df["espn_team_id"].map(club_ids),
        ).drop(columns=["espn_event_id", "espn_team_id"])
        insert(connection, "club_match_stats", club_stats)

        player_stats = tables["player_match_stats"].assign(
            match_id=lambda df: df["espn_event_id"].map(match_ids),
            player_id=lambda df: df["espn_athlete_id"].map(player_ids),
            club_id=lambda df: df["espn_team_id"].map(club_ids),
        ).drop(columns=["espn_event_id", "espn_athlete_id", "espn_team_id"])
        insert(connection, "player_match_stats", player_stats)

        events = tables["match_events"].assign(
            match_id=lambda df: df["espn_event_id"].map(match_ids),
            club_id=lambda df: df["espn_team_id"].map(club_ids),
            player_id=lambda df: df["espn_athlete_id"].map(player_ids),
            secondary_player_id=lambda df: df["secondary_espn_athlete_id"].map(player_ids),
        ).drop(columns=["espn_event_id", "espn_team_id", "espn_athlete_id", "secondary_espn_athlete_id"])
        insert(connection, "match_events", events)

        run_sql_file(connection, "views.sql")
