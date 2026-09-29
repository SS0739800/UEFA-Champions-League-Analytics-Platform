import streamlit as st

from app.components import data
from app.components.glossary import NO_XG
from app.components.sidebar import footer, page_header
from src.config import CURRENT_SEASON, season_label

st.set_page_config(page_title="UCL Analytics", layout="wide")

page_header("UCL Analytics", "Club and player analysis for the UEFA Champions League, 2012-13 to 2026-27.")

seasons = data.seasons()
current = seasons.set_index("season_year").loc[CURRENT_SEASON]
latest = data.last_updated()

left, right = st.columns([3, 2], gap="large")

with left:
    st.markdown(
        f"""
Compare clubs and players using results, shots, possession, passing and defensive
stats from every Champions League match since 2012-13. The {season_label(CURRENT_SEASON)}
season is in progress: **{current['finished']} of {current['finished'] + current['scheduled']}**
listed matches have been played, so current-season numbers rest on small samples.

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
