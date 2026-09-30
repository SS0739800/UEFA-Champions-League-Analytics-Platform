"""
Club crests for tables and headers.

Crests are the clubs' trademarks, so they aren't committed to the repository.
Each one is downloaded from ESPN's image server the first time it's needed,
shrunk to a small PNG and cached on disk (data/processed/crests, git-ignored).
If a crest can't be fetched, the page just shows no crest for that club.
"""

import base64
import io
import logging
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests
import streamlit as st
from PIL import Image

from src.config import PROCESSED_DIR

log = logging.getLogger(__name__)

CREST_URL = "https://a.espncdn.com/i/teamlogos/soccer/500/{}.png"
CACHE_DIR = PROCESSED_DIR / "crests"
CREST_SIZE = 64  # pixels; tables show them at about 20-30


def shrink(png_bytes: bytes) -> bytes:
    """Resize a crest to CREST_SIZE on its longest side, keeping transparency."""
    image = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    image.thumbnail((CREST_SIZE, CREST_SIZE), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def crest_bytes(espn_team_id: int) -> bytes | None:
    """The small crest for a club, from the disk cache or downloaded once. None if unavailable."""
    path = CACHE_DIR / f"{espn_team_id}.png"
    if path.exists():
        return path.read_bytes()
    try:
        response = requests.get(CREST_URL.format(espn_team_id), timeout=10)
        response.raise_for_status()
        small = shrink(response.content)
    except (requests.RequestException, OSError) as error:
        # A missing crest is cosmetic, so log it and carry on without one.
        log.warning("No crest for ESPN team %s: %s", espn_team_id, error)
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_bytes(small)
    return small


def data_uri(png: bytes | None) -> str | None:
    """Tables can't read local files, so crests go in as data URIs."""
    return None if png is None else "data:image/png;base64," + base64.b64encode(png).decode()


@st.cache_data(show_spinner=False)
def crest_uris(espn_team_ids: tuple[int, ...]) -> dict[int, str | None]:
    """Crests for several clubs at once. The first visit downloads them in parallel."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        crests = pool.map(crest_bytes, espn_team_ids)
    return {team_id: data_uri(png) for team_id, png in zip(espn_team_ids, crests)}


def with_crests(frame: pd.DataFrame, club_to_espn: dict[int, int], club_column: str = "club_id") -> pd.DataFrame:
    """Add a `crest` column (data URI or None) to a frame with one row per club."""
    espn_ids = frame[club_column].map(club_to_espn)
    uris = crest_uris(tuple(sorted(int(team_id) for team_id in espn_ids.dropna().unique())))
    return frame.assign(crest=[uris.get(int(team_id)) if pd.notna(team_id) else None for team_id in espn_ids])
