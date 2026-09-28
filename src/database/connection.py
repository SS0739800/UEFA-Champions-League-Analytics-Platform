from decimal import Decimal
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
        frame = pd.read_sql(text(query), connection, params=params)

    # PostgreSQL NUMERIC comes back as Decimal, and a column that's all NULL
    # comes back as object. Both break numpy maths, so make them floats.
    for column in frame.columns[frame.dtypes == object]:
        values = frame[column].dropna()
        if values.empty or all(isinstance(value, Decimal) for value in values):
            frame[column] = pd.to_numeric(frame[column], errors="coerce").astype(float)
    return frame
