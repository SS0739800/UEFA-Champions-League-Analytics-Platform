"""Load the named queries in sql/analytics_queries.sql so they live in one place."""

import re
from functools import lru_cache

import pandas as pd

from src.config import SQL_DIR
from src.database.connection import read_sql


@lru_cache(maxsize=1)
def load_queries() -> dict[str, str]:
    text = (SQL_DIR / "analytics_queries.sql").read_text(encoding="utf-8")
    # Split on the "-- name: something" lines and keep what follows each one.
    parts = re.split(r"^-- name: (\w+)\s*$", text, flags=re.MULTILINE)
    return {name: body.strip() for name, body in zip(parts[1::2], parts[2::2])}


def run_query(name: str, **params) -> pd.DataFrame:
    queries = load_queries()
    if name not in queries:
        raise KeyError(f"No query called '{name}' in analytics_queries.sql")
    return read_sql(queries[name], params)
