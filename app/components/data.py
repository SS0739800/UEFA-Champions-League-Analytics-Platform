"""
Cached database access for the dashboard.

Every page goes through load() so a database problem shows one clear message
instead of a stack trace.
"""

import pandas as pd
import streamlit as st
from sqlalchemy.exc import OperationalError, ProgrammingError

from src.database.connection import read_sql
from src.database.queries import run_query

CACHE_SECONDS = 3600


@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def query(sql: str, **params) -> pd.DataFrame:
    return read_sql(sql, params)


@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def named(name: str, **params) -> pd.DataFrame:
    return run_query(name, **params)


def load(what: str, loader, *args, **kwargs) -> pd.DataFrame:
    """Run a loader and stop the page with a readable message if the database isn't there."""
    try:
        return loader(*args, **kwargs)
    except OperationalError:
        st.error(
            f"We could not load the {what}. Check that PostgreSQL is running and the "
            "connection settings in .env are right, then refresh the page."
        )
        st.stop()
    except ProgrammingError:
        st.error(
            f"We could not load the {what} because the database tables are missing. "
            "Run `python -m src.etl.run` to build them, then refresh the page."
        )
        st.stop()


def seasons() -> pd.DataFrame:
    return load("season list", query, """
        SELECT s.start_year AS season_year, s.label AS season, s.format,
               COUNT(m.match_id) FILTER (WHERE m.status = 'finished')  AS finished,
               COUNT(m.match_id) FILTER (WHERE m.status = 'scheduled') AS scheduled
        FROM seasons s
        LEFT JOIN matches m ON m.season_id = s.season_id
        GROUP BY s.start_year, s.label, s.format
        ORDER BY s.start_year DESC
    """)


def club_matches(season_year: int | None = None) -> pd.DataFrame:
    sql = """
        SELECT cm.*, c.name AS club_name, o.name AS opponent_name
        FROM v_club_matches cm
        JOIN clubs c ON c.club_id = cm.club_id
        JOIN clubs o ON o.club_id = cm.opponent_id
    """
    if season_year is None:
        return load("match data", query, sql + " ORDER BY cm.kickoff_utc")
    return load("match data", query, sql + " WHERE cm.season_year = :season_year ORDER BY cm.kickoff_utc",
                season_year=season_year)


def club_seasons(season_year: int | None = None) -> pd.DataFrame:
    if season_year is None:
        return load("club season data", query, "SELECT * FROM v_club_season_stats")
    return load("club season data", query, "SELECT * FROM v_club_season_stats WHERE season_year = :season_year",
                season_year=season_year)


def player_seasons(season_year: int) -> pd.DataFrame:
    return load("player data", query, "SELECT * FROM v_player_season_stats WHERE season_year = :season_year",
                season_year=season_year)


def espn_team_ids() -> dict[int, int]:
    """Our club_id -> ESPN's team id. Crests are stored under ESPN's id."""
    frame = load("club list", query, "SELECT club_id, espn_team_id FROM clubs")
    return dict(zip(frame["club_id"], frame["espn_team_id"]))


def last_checked() -> pd.Timestamp | None:
    """When the pipeline last ran successfully, whether or not it found anything new."""
    frame = load("pipeline history", query,
                 "SELECT MAX(ran_at) AS ran_at FROM pipeline_runs WHERE status = 'succeeded'")
    checked = frame["ran_at"].iloc[0]
    # The database hands back its own timezone; show UTC everywhere.
    return None if pd.isna(checked) else pd.Timestamp(checked).tz_convert("UTC")


def last_updated() -> pd.Timestamp | None:
    frame = load("match data", query, "SELECT MAX(kickoff_utc) AS latest FROM matches WHERE status = 'finished'")
    return frame["latest"].iloc[0]
