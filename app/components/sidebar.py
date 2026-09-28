"""Filters shared across pages. The chosen season sticks when you change page."""

import streamlit as st

from app.components import data
from src.config import CURRENT_SEASON


def season_picker(min_season: int | None = None, allowed: set[int] | None = None, key: str = "season_year") -> int:
    seasons = data.seasons()
    if min_season is not None:
        seasons = seasons[seasons["season_year"] >= min_season]
    if allowed is not None:
        seasons = seasons[seasons["season_year"].isin(allowed)]
    seasons = seasons[seasons["finished"] > 0]

    options = seasons["season_year"].tolist()
    labels = dict(zip(seasons["season_year"], seasons["season"]))

    # A ?season=2024 link wins, then the season picked on another page, then the current season.
    from_url = st.query_params.get("season")
    remembered = int(from_url) if from_url and from_url.isdigit() else st.session_state.get("shared_season", CURRENT_SEASON)
    default = remembered if remembered in options else options[0]

    chosen = st.sidebar.selectbox(
        "Season", options, index=options.index(default), format_func=lambda year: labels[year], key=key
    )
    st.session_state["shared_season"] = chosen
    st.query_params["season"] = str(chosen)

    row = seasons.set_index("season_year").loc[chosen]
    if row["scheduled"] > 0:
        st.sidebar.caption(
            f"{labels[chosen]} is in progress: {row['finished']} matches played, {row['scheduled']} still to come."
        )
    return chosen


# Streamlit's defaults are sized for landing pages. Tone headings and metric
# numbers down so the data gets the space.
BASE_CSS = """
<style>
.block-container { padding-top: 2.5rem; padding-bottom: 3rem; max-width: 1400px; }
h1 { font-size: 1.75rem !important; font-weight: 650 !important; padding-bottom: 0.1rem !important; }
h2, h3 { font-size: 1.15rem !important; font-weight: 600 !important; }
[data-testid="stMetricValue"] { font-size: 1.45rem; }
[data-testid="stMetricLabel"] p { font-size: 0.85rem; color: #52514e; }
</style>
"""


def page_header(title: str, description: str) -> None:
    st.markdown(BASE_CSS, unsafe_allow_html=True)
    st.title(title, anchor=False)
    st.caption(description)


def footer() -> None:
    latest = data.last_updated()
    if latest is not None:
        st.sidebar.caption(f"Data: ESPN, up to {latest:%d %b %Y}.")
