"""
Run the full pipeline: download, transform, validate, load, then build the
derived tables (Elo ratings and model predictions).

    python -m src.etl.run                 # refresh from ESPN and rebuild everything
    python -m src.etl.run --offline       # rebuild from raw files already on disk
    python -m src.etl.run --extract-only  # just download raw files
    python -m src.etl.run --skip-model    # load the data but don't retrain the model
"""

import argparse
import logging
import time

from src.config import PROCESSED_DIR
from src.database.connection import get_engine
from src.etl.extract import SUMMARY_DIR, run_extract
from src.etl.load import load_all
from src.etl.transform import transform
from src.validation.checks import run_checks, stat_coverage_by_season
from src.validation.schemas import validate_tables

log = logging.getLogger("etl")


def save_processed(tables: dict, report) -> None:
    """Keep a CSV copy of each cleaned table, plus the validation output."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    for name, frame in tables.items():
        frame.to_csv(PROCESSED_DIR / f"{name}.csv", index=False)

    report.inconsistent_matches.to_csv(PROCESSED_DIR / "validation_inconsistent_scores.csv", index=False)
    coverage = stat_coverage_by_season(tables["club_match_stats"], tables["matches"])
    coverage.to_csv(PROCESSED_DIR / "validation_stat_coverage.csv", index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh the UCL analytics database.")
    parser.add_argument("--offline", action="store_true", help="don't download anything, use cached raw files")
    parser.add_argument("--extract-only", action="store_true", help="download raw files and stop")
    parser.add_argument("--skip-model", action="store_true", help="skip Elo ratings and model training")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    started = time.perf_counter()

    log.info("Step 1/5: extract")
    events = run_extract(offline=args.offline)
    if args.extract_only:
        log.info("Extract finished (%s events). Stopping here.", len(events))
        return

    log.info("Step 2/5: transform")
    tables = transform(events, SUMMARY_DIR)

    log.info("Step 3/5: validate")
    validate_tables(tables)
    report = run_checks(tables)
    save_processed(tables, report)
    report.raise_if_errors()

    log.info("Step 4/5: load into PostgreSQL")
    engine = get_engine()
    load_all(engine, tables)

    if args.skip_model:
        log.info("Skipping Elo and model training (--skip-model)")
    else:
        log.info("Step 5/5: Elo ratings and match predictions")
        from src.models.train import build_derived_tables

        build_derived_tables(engine)

    log.info("Pipeline finished in %.0f seconds", time.perf_counter() - started)


if __name__ == "__main__":
    main()
