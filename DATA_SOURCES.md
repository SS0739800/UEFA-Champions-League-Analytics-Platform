# Data sources

Everything in this project comes from one source (ESPN) plus numbers we calculate
from it. Nothing is typed in by hand and nothing is estimated to fill gaps. If a
stat isn't available for a season, it shows up as missing.

All sources below were checked on **28 September 2026**.

## Used

### ESPN site API (primary source)

| | |
|---|---|
| Scoreboard | `https://site.api.espn.com/apis/site/v2/sports/soccer/uefa.champions/scoreboard?dates=YYYY` |
| Match summary | `https://site.api.espn.com/apis/site/v2/sports/soccer/uefa.champions/summary?event=ID` |
| Accessed | 28 September 2026 |
| Seasons used | 2012-13 to 2026-27 (2026-27 is in progress) |
| Used in tables | `competitions`, `seasons`, `clubs`, `players`, `matches`, `club_match_stats`, `player_match_stats`, `match_events` |

**What it provides**

- Fixtures and results, including extra time, penalty shootouts, stage, group and leg.
- 28 team stats per match: possession, shots, shots on target, passes, crosses,
  long balls, tackles, interceptions, clearances, corners, fouls, cards, saves.
- Lineups with per-player stats: goals, assists, shots, shots on target, fouls,
  cards, saves, goals conceded. Substitutions and red cards come with a minute.
- Key events: goals (with assister), penalties, own goals, cards, substitutions.

**Usage notes**

This is ESPN's public site API, the one their website calls. It is not
documented or officially supported, and ESPN's terms of use cover it. This
project uses it for non-commercial, educational analysis. The raw responses are
cached in `data/raw/` and are **not** committed to git. Requests are rate
limited (one every ~0.4s plus retries with backoff), and finished matches are
only downloaded once.

**Known limitations**

- **No expected goals (xG).** ESPN doesn't publish xG for the Champions League,
  and none of the other sources below had it for the full competition. Every
  "finishing" metric in the project is based on shots and shots on target, and
  the UI says so.
- **No player-level passing or defensive stats.** Tackles, interceptions and
  passes only exist at team level.
- **Some team stats are missing for older seasons.** ESPN returns 0 instead of
  leaving them out. The pipeline measures this per season (see
  `data/processed/validation_stat_coverage.csv`) and treats a stat as missing when
  fewer than half of team-matches in that season have a non-zero value:

  | Stat | Missing for |
  |---|---|
  | Interceptions | 2012-13 to 2017-18 |
  | Passes, crosses, long balls, tackles, clearances | 2017-18 |

- **`penaltyKickGoals` is wrong in some seasons.** In 2015-16 it holds the
  team's total goals (Real Madrid 4-0 Shakhtar shows 4 penalty goals, but there
  were 2). We don't use that field. Penalties are counted from the key events.
- **A few player stats disagree with the key events.** In one match (Club
  Brugge 2-1 Sporting CP, 10 Dec 2024) an own goal is also counted as a goal in
  the player's stats. The pipeline flags matches like this in
  `data/processed/validation_inconsistent_scores.csv` and keeps them, since it's
  one match in 1,890. A handful of penalties aren't counted as shots, so
  non-penalty shot counts are floored at zero.
- **Some 2018-19 rosters list the goalkeeper twice** with identical stats. Exact
  duplicates are dropped during the transform.
- **Minutes played are approximate.** ESPN doesn't give minutes directly. We
  work them out from substitution and red card times, ignoring added time, so a
  player on the pitch for all of a 90+6 match is recorded as 90 minutes.
- **Substitutes have no position in the match data** ("SUB"). We use the
  position group the player most often starts in. Players who never start in
  our data are marked `UNK`.
- **Attendance** is 0 both for unknown values and for closed-door games in
  2020-21, so zeros are stored as NULL and attendance isn't used in the analysis.
- **Neutral venues** are rarely flagged by ESPN. We mark every final and the
  2019-20 quarter-finals and semi-finals (the Lisbon tournament) as neutral.
  Some 2020-21 knockout games were moved to neutral grounds because of COVID
  travel rules. Those are not flagged.
- **No player dates of birth**, so there are no age-based checks or metrics.
- **Qualifying rounds are excluded.** ESPN only has them for some seasons, so
  including them would make seasons hard to compare.
- **2011-12** only has knockout games, so it's left out.

### Calculated in this project

| Table / view | What | Where |
|---|---|---|
| `club_elo` | Elo ratings from UCL results only | `src/features/elo.py` |
| `match_predictions`, `model_evaluation` | Model output and backtest scores | `src/models/` |
| `v_group_standings`, `v_club_season_stats`, `v_player_season_stats` | Season tables and per-90 stats | `sql/views.sql` |

## Checked but not used

| Source | What it has | Why it isn't used |
|---|---|---|
| [transfermarkt-datasets](https://github.com/dcaribou/transfermarkt-datasets) (CC0) | UCL results, lineups, player minutes, goals and assists, 2012-13 onwards | No team match stats (shots, possession). Last update was 5 Sep 2026, so it has no 2026-27 matches, and the 2025-26 final was missing. It would be a good cross-check for scores and minutes later. |
| [FBref](https://fbref.com) | Detailed stats | Returned HTTP 403 to automated requests, and its terms don't allow scraping. |
| [football-data.org](https://www.football-data.org) | Fixtures, results, standings | Needs an API key; the free tier has no match stats. |
| [StatsBomb open data](https://github.com/statsbomb/open-data) | Event data with xG | Only UCL finals (one match per season). Not enough for club or player analysis. |
| [ClubElo](http://clubelo.com) | Elo ratings using domestic and European games | API returned HTTP 502 when checked. We calculate our own UCL-only Elo instead. |
| [Understat](https://understat.com) | xG | Covers domestic leagues only, not the Champions League. |
