"""Project-wide settings: paths, database connection and a few analysis constants."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
ESPN_RAW_DIR = RAW_DIR / "espn"
PROCESSED_DIR = DATA_DIR / "processed"
SQL_DIR = PROJECT_ROOT / "sql"

# ESPN's public site API. It is undocumented, so see DATA_SOURCES.md for caveats.
ESPN_BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/uefa.champions"

# Seasons are named by the year they start in (2026 means 2026-27).
# ESPN only has knockout games for 2011-12, so 2012-13 is the first full season.
FIRST_SEASON = 2012
CURRENT_SEASON = 2026

# Default minimum minutes for per-90 tables: three full matches.
DEFAULT_MIN_MINUTES = 270


def season_label(start_year: int) -> str:
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def database_url() -> str:
    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"]

    user = os.getenv("POSTGRES_USER", "ucl")
    password = os.getenv("POSTGRES_PASSWORD", "ucl")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    name = os.getenv("POSTGRES_DB", "ucl_analytics")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"
