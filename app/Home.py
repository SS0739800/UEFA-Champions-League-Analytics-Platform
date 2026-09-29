import sys
from pathlib import Path

# `streamlit run` only puts app/ on the import path, so add the project root for `app` and `src`.
PROJECT_ROOT = next(path for path in Path(__file__).resolve().parents if (path / "src").is_dir())
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from app.components import data
from app.components.glossary import NO_XG
from app.components.sidebar import footer, page_header

st.set_page_config(page_title="UCL Analytics", layout="wide")

seasons = data.seasons()
# Seasons come newest first. Use the latest one in the data, which in July and
# August is still last season until the new fixtures are published.
newest = seasons.iloc[0]
oldest = seasons.iloc[-1]
latest = data.last_updated()

page_header(
    "UCL Analytics",
    f"Club and player analysis for the UEFA Champions League, {oldest['season']} to {newest['season']}.",
)

if newest["scheduled"] > 0:
    season_note = (
        f"The {newest['season']} season is in progress: **{newest['finished']} of "
        f"{newest['finished'] + newest['scheduled']}** listed matches have been played, so current-season "
        "numbers rest on small samples."
    )
else:
    season_note = f"The latest season in the data is {newest['season']}, which is complete."

left, right = st.columns([3, 2], gap="large")

with left:
    st.markdown(
        f"""
Compare clubs and players using results, shots, possession, passing and defensive
stats from every Champions League match since {oldest['season']}. {season_note}

| Page | What it answers |
|---|---|
| Competition Overview | How is the season going? Standings, results, trends and our performance index. |
| Club Analytics | How is one club doing, home and away, against whom, and compared with other clubs? |
| Player Intelligence | Who scores and creates the most per 90 minutes, and how sure can we be? |
| Tactical Analysis | Which clubs play in similar ways, based on possession, passing and defending? |
| Finishing & Efficiency | Who turns shots into goals more often than the average finisher? |
| Prediction Lab | How well can pre-match information predict results, and what does the model say next? |
"""
    )

with right:
    st.subheader("Coverage", anchor=False)
    coverage = seasons.assign(
        matches=seasons["finished"],
        format=seasons["format"].map({"group_stage": "Groups of four", "league_phase": "36-team league"}),
    )[["season", "format", "matches"]]
    st.dataframe(
        coverage,
        hide_index=True,
        width="stretch",
        height=300,
        column_config={
            "season": "Season",
            "format": "First phase",
            "matches": st.column_config.NumberColumn("Matches played", format="%d"),
        },
    )
    if latest is not None:
        st.caption(f"Latest match in the database: {latest:%d %b %Y}. Qualifying rounds are not included.")

st.divider()
st.markdown("**Before you read too much into the numbers**")
st.markdown(
    f"""
- {NO_XG}
- Some team stats are missing for older seasons (interceptions before 2018-19; passing, crossing and
  tackling in 2017-18) and for a few hundred single team-matches. Those show as blank, not zero.
- Player minutes are worked out from substitution times and ignore added time.
- From 2024-25 the first phase changed from eight groups of four to one 36-team league,
  so compare group-stage numbers across that line with care.
"""
)

footer()
