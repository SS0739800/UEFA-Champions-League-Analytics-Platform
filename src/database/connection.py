from functools import lru_cache

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from src.config import database_url


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(database_url(), pool_pre_ping=True)


def read_sql(query: str, params: dict | None = None) -> pd.DataFrame:
    with get_engine().connect() as connection:
        return pd.read_sql(text(query), connection, params=params)
