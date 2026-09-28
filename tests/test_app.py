"""
Smoke test: every dashboard page runs without an exception for a few different seasons.

Needs a loaded database (python -m src.etl.run), so it's skipped otherwise.
"""

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

from src.database.connection import get_engine

PAGES = ["app/Home.py"] + sorted(str(path.as_posix()) for path in Path("app/pages").glob("*.py"))


def database_has_matches() -> bool:
    try:
        with get_engine().connect() as connection:
            return connection.execute(text("SELECT COUNT(*) FROM matches")).scalar() > 0
    except (OperationalError, ProgrammingError):
        return False


pytestmark = pytest.mark.skipif(not database_has_matches(), reason="needs a loaded database")


@pytest.mark.parametrize("page", PAGES)
@pytest.mark.parametrize("season", ["2026", "2024", "2017"])
def test_page_runs(page, season):
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(page, default_timeout=180)
    app.query_params["season"] = season
    app.run()
    assert not app.exception, [error.value for error in app.exception]
