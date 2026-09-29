"""
Load the transformed tables into PostgreSQL.

Two ways in:
  load_all     drop and rebuild everything from scratch (python -m src.etl.run)
  load_update  add new fixtures and newly finished matches, leave the rest alone
               (python -m src.etl.run --update)

Both run in one transaction, so if anything fails the database stays as it was.
"""

import logging

import numpy as np
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


def records(frame: pd.DataFrame) -> list[dict]:
    """
    Rows as plain dicts for executemany: NaN becomes None, and numpy numbers
    become normal Python ones so the database driver knows what to do with them.
    """
    rows = frame.astype(object).where(frame.notna(), None).to_dict("records")
    return [{key: value.item() if isinstance(value, np.generic) else value for key, value in row.items()}
            for row in rows]


def season_rows(competition_id: int, season_years) -> pd.DataFrame:
    season_years = sorted(int(year) for year in season_years)
    return pd.DataFrame({
        "competition_id": competition_id,
        "start_year": season_years,
        "label": [season_label(year) for year in season_years],
        # The 36-team league phase replaced groups from 2024-25.
        "format": ["league_phase" if year >= 2024 else "group_stage" for year in season_years],
    })


def match_rows(matches: pd.DataFrame, season_ids: dict, club_ids: dict) -> pd.DataFrame:
    """Swap ESPN ids for our ids so the frame matches the matches table."""
    return matches.assign(
        season_id=matches["season_year"].map(season_ids),
        home_club_id=matches["home_espn_id"].map(club_ids),
        away_club_id=matches["away_espn_id"].map(club_ids),
        winner_club_id=matches["winner_espn_id"].map(club_ids),
    ).drop(columns=["season_year", "home_espn_id", "away_espn_id", "winner_espn_id"])


def insert_match_details(connection: Connection, tables: dict, match_ids: dict, club_ids: dict,
                         player_ids: dict) -> None:
    """Insert team stats, player stats and key events, swapping ESPN ids for ours."""
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


def load_all(engine: Engine, tables: dict[str, pd.DataFrame]) -> None:
    """Rebuild the database from the transformed tables."""
    with engine.begin() as connection:
        run_sql_file(connection, "schema.sql")

        competition_id = connection.execute(
            text("INSERT INTO competitions (name, espn_slug) VALUES (:name, :slug) RETURNING competition_id"),
            {"name": COMPETITION_NAME, "slug": COMPETITION_SLUG},
        ).scalar_one()

        insert(connection, "seasons", season_rows(competition_id, tables["matches"]["season_year"].unique()))
        season_ids = id_map(connection, "seasons", "season_id", "start_year")

        insert(connection, "clubs", tables["clubs"])
        club_ids = id_map(connection, "clubs", "club_id", "espn_team_id")

        insert(connection, "players", tables["players"])
        player_ids = id_map(connection, "players", "player_id", "espn_athlete_id")

        insert(connection, "matches", match_rows(tables["matches"], season_ids, club_ids))
        match_ids = id_map(connection, "matches", "match_id", "espn_event_id")

        insert_match_details(connection, tables, match_ids, club_ids, player_ids)
        run_sql_file(connection, "views.sql")


def finished_event_ids(engine: Engine) -> set[int]:
    """ESPN ids of matches already loaded as finished. An update skips these."""
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT espn_event_id FROM matches WHERE status = 'finished'")).all()
    return {int(row[0]) for row in rows}


def usual_position_groups(engine: Engine) -> pd.Series:
    """Each player's most common starting position group, keyed by ESPN athlete id."""
    with engine.connect() as connection:
        frame = pd.read_sql(text("""
            SELECT p.espn_athlete_id, MODE() WITHIN GROUP (ORDER BY pms.position_group) AS position_group
            FROM player_match_stats pms
            JOIN players p ON p.player_id = pms.player_id
            WHERE pms.is_starter AND pms.position_group <> 'UNK'
            GROUP BY p.espn_athlete_id
        """), connection)
    return frame.set_index("espn_athlete_id")["position_group"]


def load_update(engine: Engine, tables: dict[str, pd.DataFrame]) -> int:
    """
    Add or update the matches in `tables` without touching anything else.

    Clubs, players and matches are matched on their ESPN ids. For finished
    matches, any existing stats and events are replaced, so running the same
    update twice gives the same result. Returns the number of finished matches loaded.
    """
    matches = tables["matches"]
    finished = matches.loc[matches["status"] == "finished", "espn_event_id"]

    with engine.begin() as connection:
        competition_id = connection.execute(
            text("SELECT competition_id FROM competitions WHERE espn_slug = :slug"), {"slug": COMPETITION_SLUG}
        ).scalar()
        if competition_id is None:
            raise RuntimeError("The database is empty. Run a full load first: python -m src.etl.run")

        connection.execute(
            text("""
                INSERT INTO seasons (competition_id, start_year, label, format)
                VALUES (:competition_id, :start_year, :label, :format)
                ON CONFLICT (competition_id, start_year) DO NOTHING
            """),
            records(season_rows(competition_id, matches["season_year"].unique())),
        )
        connection.execute(
            text("""
                INSERT INTO clubs (espn_team_id, name, short_name, abbreviation)
                VALUES (:espn_team_id, :name, :short_name, :abbreviation)
                ON CONFLICT (espn_team_id) DO UPDATE
                SET name = EXCLUDED.name, short_name = EXCLUDED.short_name, abbreviation = EXCLUDED.abbreviation
            """),
            records(tables["clubs"]),
        )
        if not tables["players"].empty:
            connection.execute(
                text("""
                    INSERT INTO players (espn_athlete_id, full_name) VALUES (:espn_athlete_id, :full_name)
                    ON CONFLICT (espn_athlete_id) DO UPDATE SET full_name = EXCLUDED.full_name
                """),
                records(tables["players"]),
            )

        season_ids = id_map(connection, "seasons", "season_id", "start_year")
        club_ids = id_map(connection, "clubs", "club_id", "espn_team_id")
        player_ids = id_map(connection, "players", "player_id", "espn_athlete_id")

        rows = match_rows(matches, season_ids, club_ids)
        columns = [column for column in rows.columns if column != "espn_event_id"]
        connection.execute(
            text(f"""
                INSERT INTO matches (espn_event_id, {", ".join(columns)})
                VALUES (:espn_event_id, {", ".join(":" + column for column in columns)})
                ON CONFLICT (espn_event_id) DO UPDATE
                SET {", ".join(f"{column} = EXCLUDED.{column}" for column in columns)}
            """),
            records(rows),
        )
        match_ids = id_map(connection, "matches", "match_id", "espn_event_id")

        if len(finished):
            # Clear out anything from an earlier, partial load of these matches before inserting.
            ids = [int(match_ids[event_id]) for event_id in finished]
            for table in ("club_match_stats", "player_match_stats", "match_events"):
                connection.execute(text(f"DELETE FROM {table} WHERE match_id = ANY(:ids)"), {"ids": ids})
            insert_match_details(connection, tables, match_ids, club_ids, player_ids)

    log.info("Update loaded %s fixtures, %s of them finished", len(matches), len(finished))
    return len(finished)


def record_run(engine: Engine, mode: str, status: str, finished_matches: int = 0, note: str | None = None) -> None:
    """Log a pipeline run. The dashboard shows when data was last checked."""
    with engine.begin() as connection:
        connection.execute(
            text("""
                INSERT INTO pipeline_runs (mode, status, finished_matches, note)
                VALUES (:mode, :status, :finished_matches, :note)
            """),
            {"mode": mode, "status": status, "finished_matches": finished_matches,
             "note": note[:500] if note else None},
        )

