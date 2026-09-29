"""
Download raw Champions League data from ESPN and save it untouched under data/raw/espn.

Two endpoints are used:
  scoreboard?dates=YYYY   every fixture played (or scheduled) in a calendar year
  summary?event=ID        box score, lineups and key events for one match

Raw files are cached. Past years and finished matches never change, so they are
only downloaded once. The current year's scoreboard is always refreshed.
"""

import json
import logging
import time
from datetime import date
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.config import CURRENT_SEASON, ESPN_BASE_URL, ESPN_RAW_DIR, FIRST_SEASON

log = logging.getLogger(__name__)

SCOREBOARD_DIR = ESPN_RAW_DIR / "scoreboard"
SUMMARY_DIR = ESPN_RAW_DIR / "summary"

# Be polite. There is no published rate limit, so keep it slow.
REQUEST_PAUSE_SECONDS = 0.4


def make_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.headers["User-Agent"] = "ucl-analytics portfolio project (non-commercial)"
    return session


def get_json(session: requests.Session, url: str, params: dict) -> dict:
    response = session.get(url, params=params, timeout=30)
    if response.status_code in (403, 429):
        # After the first full download ESPN blocked every request from the machine for a
        # few hours, then kept refusing just this User-Agent for longer.
        raise RuntimeError(
            f"ESPN refused the request ({response.status_code}) for {response.url}. It sometimes blocks "
            "this client for a while after a large download. Try again later, or rebuild from the raw "
            "files you already have with: python -m src.etl.run --offline"
        )
    response.raise_for_status()
    time.sleep(REQUEST_PAUSE_SECONDS)
    return response.json()


def save_json(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def calendar_years_to_fetch() -> list[int]:
    # A season starting in 2012 has games in 2012 and 2013, so we need one
    # extra year on the end. Never ask for years that haven't started yet.
    last_year = min(CURRENT_SEASON + 1, date.today().year)
    return list(range(FIRST_SEASON, last_year + 1))


def fetch_scoreboards(session: requests.Session, refresh_years: set[int]) -> list[dict]:
    """Return every event from the yearly scoreboards, downloading any we don't have."""
    events = {}
    for year in calendar_years_to_fetch():
        path = SCOREBOARD_DIR / f"{year}.json"
        if year in refresh_years or not path.exists():
            log.info("Downloading scoreboard for %s", year)
            payload = get_json(session, f"{ESPN_BASE_URL}/scoreboard", {"dates": year, "limit": 1000})
            save_json(payload, path)
        else:
            payload = load_json(path)

        # The same event can show up in two yearly files, so key on the id.
        for event in payload.get("events", []):
            events[event["id"]] = event

    log.info("Found %s events across all scoreboards", len(events))
    return list(events.values())


def fetch_summaries(session: requests.Session, event_ids: list[str]) -> None:
    """Download match summaries we don't already have on disk."""
    missing = [event_id for event_id in event_ids if not (SUMMARY_DIR / f"{event_id}.json").exists()]
    log.info("%s match summaries cached, %s to download", len(event_ids) - len(missing), len(missing))

    for count, event_id in enumerate(missing, start=1):
        payload = get_json(session, f"{ESPN_BASE_URL}/summary", {"event": event_id})
        save_json(payload, SUMMARY_DIR / f"{event_id}.json")
        if count % 100 == 0:
            log.info("Downloaded %s of %s summaries", count, len(missing))


def run_extract(offline: bool = False) -> list[dict]:
    """
    Make sure all the raw files we need are on disk and return the scoreboard events.

    With offline=True nothing is downloaded, which is handy for rebuilding the
    database from files you already have.
    """
    from src.etl.transform import is_main_tournament_event

    if offline:
        paths = sorted(SCOREBOARD_DIR.glob("*.json"))
        if not paths:
            raise FileNotFoundError(
                f"No raw scoreboard files in {SCOREBOARD_DIR}. Run the pipeline once without --offline."
            )
        events = {}
        for path in paths:
            for event in load_json(path).get("events", []):
                events[event["id"]] = event
        return list(events.values())

    session = make_session()
    # Only the current calendar year can still change.
    events = fetch_scoreboards(session, refresh_years={date.today().year})

    finished_ids = [
        event["id"]
        for event in events
        if is_main_tournament_event(event) and event["status"]["type"]["completed"]
    ]
    fetch_summaries(session, finished_ids)
    return events
