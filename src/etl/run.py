"""
Run the pipeline: download, transform, validate, load, then build the derived
tables (Elo ratings and model predictions).

    python -m src.etl.run                 # refresh from ESPN and rebuild everything
    python -m src.etl.run --offline       # rebuild from raw files already on disk
    python -m src.etl.run --update        # only add new fixtures and results (used by the schedule)
    python -m src.etl.run --extract-only  # just download raw files
    python -m src.etl.run --skip-model    # load the data but don't retrain the model

Every run is logged in the pipeline_runs table, including ones that fail.
"""

import argparse
import logging
import time

from src.config import PROCESSED_DIR
from src.database.connection import get_engine
from src.etl.extract import SUMMARY_DIR, run_extract, run_extract_update
from src.etl.load import finished_event_ids, load_all, load_update, record_run, usual_position_groups
from src.etl.transform import transform
from src.validation.checks import blank_missing_stats, run_checks, stat_coverage_by_season
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


def build_model_tables(engine, skip_model: bool) -> None:
    if skip_model:
        log.info("Skipping Elo and model training (--skip-model)")
        return
    from src.models.train import build_derived_tables

    build_derived_tables(engine)


def full_run(engine, args) -> int:
    log.info("Step 1/5: extract")
    events = run_extract(offline=args.offline)

    log.info("Step 2/5: transform")
    tables = transform(events, SUMMARY_DIR)

    log.info("Step 3/5: validate")
    validate_tables(tables)
    report = run_checks(tables)
    save_processed(tables, report)
    report.raise_if_errors()
    # Stats ESPN never recorded come through as 0. Store them as NULL instead.
    tables["club_match_stats"] = blank_missing_stats(tables["club_match_stats"], tables["matches"])

    log.info("Step 4/5: load into PostgreSQL")
    load_all(engine, tables)

    log.info("Step 5/5: Elo ratings and match predictions")
    build_model_tables(engine, args.skip_model)
    return int((tables["matches"]["status"] == "finished").sum())


def update_run(engine, args) -> int:
    log.info("Step 1/5: check the database and download anything new")
    events = run_extract_update(already_finished=finished_event_ids(engine))
    if not events:
        log.info("Nothing new to load")
        return 0

    log.info("Step 2/5: transform")
    tables = transform(events, SUMMARY_DIR, known_groups=usual_position_groups(engine))

    log.info("Step 3/5: validate")
    validate_tables(tables)
    run_checks(tables, whole_seasons=False).raise_if_errors()
    tables["club_match_stats"] = blank_missing_stats(
        tables["club_match_stats"], tables["matches"], whole_seasons=False
    )

    log.info("Step 4/5: load into PostgreSQL")
    finished = load_update(engine, tables)

    log.info("Step 5/5: Elo ratings and match predictions")
    build_model_tables(engine, args.skip_model)
    return finished


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh the UCL analytics database.")
    parser.add_argument("--offline", action="store_true", help="don't download anything, use cached raw files")
    parser.add_argument("--update", action="store_true", help="only add new fixtures and results")
    parser.add_argument("--extract-only", action="store_true", help="download raw files and stop")
    parser.add_argument("--skip-model", action="store_true", help="skip Elo ratings and model training")
    args = parser.parse_args()
    if args.update and args.offline:
        parser.error("--update needs to talk to ESPN, so it can't be combined with --offline")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    started = time.perf_counter()

    if args.extract_only:
        events = run_extract(offline=args.offline)
        log.info("Extract finished (%s events). Stopping here.", len(events))
        return

    engine = get_engine()
    mode = "update" if args.update else "full"
    try:
        finished = update_run(engine, args) if args.update else full_run(engine, args)
    except Exception as error:
        # Log the failure in the database too, then let the error through as normal.
        try:
            record_run(engine, mode, "failed", note=f"{type(error).__name__}: {error}")
        except Exception:
            # The database itself may be what's broken. Don't hide the original error behind this one.
            log.warning("Couldn't record the failed run in pipeline_runs")
        raise

    record_run(engine, mode, "succeeded", finished_matches=finished)
    log.info("Pipeline finished in %.0f seconds", time.perf_counter() - started)


if __name__ == "__main__":
    main()
