"""Filters shared across pages. The chosen season sticks when you change page."""

import html

import streamlit as st

from app.components import data
from src.config import CURRENT_SEASON, PROJECT_ROOT

# Tab icon: our own navy-and-blue star, not UEFA's logo (see the README).
PAGE_ICON = str(PROJECT_ROOT / "app" / "static" / "favicon.png")


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
    if from_url and from_url.isdigit():
        remembered = int(from_url)
    else:
        remembered = st.session_state.get("shared_season", CURRENT_SEASON)
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
# numbers down so the data gets the space, and add the navy header band.
BASE_CSS = """
<style>
.block-container { padding-top: 2rem; padding-bottom: 3rem; max-width: 1400px; }
h1, h2, h3 { font-family: 'Barlow Condensed', system-ui, sans-serif !important; letter-spacing: 0.01em; }
h2, h3 { font-size: 1.35rem !important; font-weight: 700 !important; text-transform: uppercase; }
[data-testid="stMetricValue"] { font-family: 'Barlow Condensed', system-ui, sans-serif; font-size: 1.9rem;
                                font-weight: 700; }
[data-testid="stMetricLabel"] p { font-size: 0.8rem; color: #8b93c2; text-transform: uppercase;
                                  letter-spacing: 0.04em; }
.page-band { background: #111a45; border-bottom: 3px solid #3987e5; border-radius: 4px;
             padding: 1.1rem 1.4rem 0.9rem; margin-bottom: 1.4rem; }
.page-band .page-title { font-family: 'Barlow Condensed', system-ui, sans-serif; font-weight: 700;
                         font-size: 2.1rem; line-height: 1.1; text-transform: uppercase; color: #f3f5ff;
                         letter-spacing: 0.02em; margin: 0; }
.page-band .page-description { color: #c2c8ea; font-size: 0.95rem; margin: 0.3rem 0 0; }
</style>
"""


def page_header(title: str, description: str) -> None:
    st.markdown(BASE_CSS, unsafe_allow_html=True)
    st.markdown(
        f'<div class="page-band"><p class="page-title">{html.escape(title)}</p>'
        f'<p class="page-description">{html.escape(description)}</p></div>',
        unsafe_allow_html=True,
    )


def footer() -> None:
    latest = data.last_updated()
    checked = data.last_checked()
    if latest is not None:
        note = f"Data: ESPN, latest match {latest:%d %b %Y}."
        if checked is not None:
            note += f" Last checked for new results {checked:%d %b %Y, %H:%M} UTC."
        st.sidebar.caption(note)
    st.sidebar.caption("Unofficial fan-made analytics. Not affiliated with or endorsed by UEFA.")
