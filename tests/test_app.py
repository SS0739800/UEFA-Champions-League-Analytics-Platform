"""
Smoke test: every dashboard page runs without an exception for a few different seasons.

Needs a loaded database (python -m src.etl.run), so it's skipped otherwise.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

from src.config import PROJECT_ROOT
from src.database.connection import get_engine

APP_DIR = PROJECT_ROOT / "app"
PAGES = ["Home.py"] + sorted(f"pages/{path.name}" for path in (APP_DIR / "pages").glob("*.py"))


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

    app = AppTest.from_file(str(APP_DIR / page), default_timeout=180)
    app.query_params["season"] = season
    app.run()
    assert not app.exception, [error.value for error in app.exception]
