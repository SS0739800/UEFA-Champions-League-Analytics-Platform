"""
Checks that need more than one table.

Two kinds of problem come out of here:
  errors    structural problems (missing keys, duplicates). The pipeline stops.
  warnings  a handful of matches where ESPN's numbers don't agree with each other.
            These are logged and written to a report. If there are too many of
            them the pipeline stops, because that points at a parsing bug.
"""

import logging
from dataclasses import dataclass, field

import pandas as pd

log = logging.getLogger(__name__)

# More than this share of finished matches failing a consistency check is treated as an error.
MAX_INCONSISTENT_SHARE = 0.02

# A stat is "unreliable" for a season when fewer than this share of team-matches have a non-zero value.
MIN_NONZERO_SHARE = 0.5


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    inconsistent_matches: pd.DataFrame = field(default_factory=pd.DataFrame)

    def raise_if_errors(self) -> None:
        if self.errors:
            raise ValueError("Data validation failed:\n  - " + "\n  - ".join(self.errors))


def check_foreign_keys(tables: dict, report: ValidationReport) -> None:
    club_ids = set(tables["clubs"]["espn_team_id"])
    player_ids = set(tables["players"]["espn_athlete_id"])
    match_ids = set(tables["matches"]["espn_event_id"])

    def missing(values, known):
        return sorted(set(values.dropna().astype(int)) - known)

    matches = tables["matches"]
    references = {
        "matches.home club": missing(matches["home_espn_id"], club_ids),
        "matches.away club": missing(matches["away_espn_id"], club_ids),
        "club_match_stats.club": missing(tables["club_match_stats"]["espn_team_id"], club_ids),
        "club_match_stats.match": missing(tables["club_match_stats"]["espn_event_id"], match_ids),
        "player_match_stats.player": missing(tables["player_match_stats"]["espn_athlete_id"], player_ids),
        "player_match_stats.club": missing(tables["player_match_stats"]["espn_team_id"], club_ids),
        "player_match_stats.match": missing(tables["player_match_stats"]["espn_event_id"], match_ids),
        "match_events.match": missing(tables["match_events"]["espn_event_id"], match_ids),
        "match_events.club": missing(tables["match_events"]["espn_team_id"], club_ids),
        "match_events.player": missing(tables["match_events"]["espn_athlete_id"], player_ids),
    }
    for reference, ids in references.items():
        if ids:
            report.errors.append(f"{reference} points at ids that don't exist: {ids[:10]}")


def check_duplicates(tables: dict, report: ValidationReport) -> None:
    matches = tables["matches"].copy()
    matches["match_date"] = matches["kickoff_utc"].dt.date

    same_fixture = matches.duplicated(["home_espn_id", "away_espn_id", "match_date"], keep=False)
    if same_fixture.any():
        ids = matches.loc[same_fixture, "espn_event_id"].tolist()
        report.errors.append(f"Same fixture listed more than once on one day: events {ids[:10]}")

    # No club plays two UCL games on the same day.
    per_club = pd.concat([
        matches[["espn_event_id", "match_date", "home_espn_id"]].rename(columns={"home_espn_id": "club"}),
        matches[["espn_event_id", "match_date", "away_espn_id"]].rename(columns={"away_espn_id": "club"}),
    ])
    double_booked = per_club.duplicated(["club", "match_date"], keep=False)
    if double_booked.any():
        ids = per_club.loc[double_booked, "espn_event_id"].unique().tolist()
        report.errors.append(f"A club has two matches on the same day: events {ids[:10]}")

    # The same club name under two ESPN ids usually means a club was split by mistake.
    clubs = tables["clubs"]
    repeated_names = clubs[clubs.duplicated("name", keep=False)]
    if not repeated_names.empty:
        report.errors.append(f"Club names used by more than one ESPN id: {sorted(set(repeated_names['name']))}")


def check_stats_present(tables: dict, report: ValidationReport) -> None:
    finished = tables["matches"].query("status == 'finished'")
    stats_rows = tables["club_match_stats"].groupby("espn_event_id").size()
    missing = finished.loc[~finished["espn_event_id"].isin(stats_rows[stats_rows == 2].index), "espn_event_id"]
    if len(missing):
        report.warnings.append(f"{len(missing)} finished matches don't have team stats for both sides")

    players = tables["player_match_stats"].groupby("espn_event_id")["espn_team_id"].nunique()
    no_lineups = finished.loc[~finished["espn_event_id"].isin(players[players == 2].index), "espn_event_id"]
    if len(no_lineups):
        report.warnings.append(f"{len(no_lineups)} finished matches don't have lineups for both sides")


def check_score_consistency(tables: dict, report: ValidationReport) -> None:
    """
    Compare the final score with the goals we can see in the other tables.

    For each club in each finished match:
      - goal events credited to the club should equal its score
      - its players' goals plus own goals by the opponent should equal its score
    """
    matches = tables["matches"].query("status == 'finished'")
    per_club = pd.concat([
        matches[["espn_event_id", "home_espn_id", "home_goals"]].set_axis(["espn_event_id", "club", "goals"], axis=1),
        matches[["espn_event_id", "away_espn_id", "away_goals"]].set_axis(["espn_event_id", "club", "goals"], axis=1),
    ])

    events = tables["match_events"]
    goal_events = (
        events[events["event_type"].isin(["goal", "penalty_goal", "own_goal"])]
        .groupby(["espn_event_id", "espn_team_id"]).size()
        .rename("event_goals")
    )

    player_stats = tables["player_match_stats"]
    player_goals = player_stats.groupby(["espn_event_id", "espn_team_id"])["goals"].sum().rename("player_goals")
    own_goals = (
        events[events["event_type"] == "own_goal"]
        .groupby(["espn_event_id", "espn_team_id"]).size()
        .rename("own_goals_for")
    )

    combined = (
        per_club.set_index(["espn_event_id", "club"])
        .join(goal_events.rename_axis(["espn_event_id", "club"]))
        .join(player_goals.rename_axis(["espn_event_id", "club"]))
        .join(own_goals.rename_axis(["espn_event_id", "club"]))
        .fillna({"event_goals": 0, "own_goals_for": 0})
        .reset_index()
    )
    # Only compare player goals where we actually have a lineup.
    combined["player_side_goals"] = combined["player_goals"] + combined["own_goals_for"]

    events_off = combined["event_goals"] != combined["goals"]
    players_off = combined["player_goals"].notna() & (combined["player_side_goals"] != combined["goals"])
    bad = combined[events_off | players_off]

    bad_matches = bad["espn_event_id"].nunique()
    share = bad_matches / max(len(matches), 1)
    report.inconsistent_matches = bad
    if bad_matches:
        message = (
            f"{bad_matches} of {len(matches)} finished matches ({share:.1%}) have goal counts "
            f"that don't match the score"
        )
        if share > MAX_INCONSISTENT_SHARE:
            report.errors.append(message + ". That's too many, probably a parsing bug.")
        else:
            report.warnings.append(message)


def check_possession_totals(tables: dict, report: ValidationReport) -> None:
    possession = tables["club_match_stats"].groupby("espn_event_id")["possession_pct"].agg(["sum", "count"])
    both_sides = possession[possession["count"] == 2]
    off = both_sides[(both_sides["sum"] - 100).abs() > 1.5]
    if len(off):
        report.warnings.append(f"{len(off)} matches where possession doesn't add up to 100%")


def stat_coverage_by_season(club_match_stats: pd.DataFrame, matches: pd.DataFrame) -> pd.DataFrame:
    """
    Share of team-matches in each season with a non-zero value for each stat.

    Some stats are clearly missing for older seasons (for example interceptions
    are 0 for every team in 2012-13), so the analysis needs to know which
    stat/season combinations to leave out.
    """
    stat_columns = [c for c in club_match_stats.columns if c not in ("espn_event_id", "espn_team_id")]
    merged = club_match_stats.merge(matches[["espn_event_id", "season_year"]], on="espn_event_id")
    nonzero = merged[stat_columns].fillna(0).ne(0)
    nonzero["season_year"] = merged["season_year"]
    coverage = nonzero.groupby("season_year").mean()
    return coverage.reset_index().melt(id_vars="season_year", var_name="stat", value_name="nonzero_share")


# These are legitimately zero in most matches, so a low share doesn't mean missing data.
USUALLY_ZERO_STATS = {"red_cards", "offsides"}


def check_stat_coverage(tables: dict, report: ValidationReport) -> pd.DataFrame:
    coverage = stat_coverage_by_season(tables["club_match_stats"], tables["matches"])
    gaps = missing_stat_seasons(coverage).merge(coverage, on=["season_year", "stat"])
    for row in gaps.itertuples():
        report.warnings.append(
            f"'{row.stat}' is zero in {1 - row.nonzero_share:.0%} of {row.season_year} team-matches, "
            "treating it as missing for that season"
        )
    return coverage


def missing_stat_seasons(coverage: pd.DataFrame) -> pd.DataFrame:
    """The (season, stat) pairs we treat as missing rather than genuinely zero."""
    return coverage[
        (coverage["nonzero_share"] < MIN_NONZERO_SHARE) & ~coverage["stat"].isin(USUALLY_ZERO_STATS)
    ][["season_year", "stat"]]


def blank_missing_stats(club_match_stats: pd.DataFrame, matches: pd.DataFrame) -> pd.DataFrame:
    """
    Replace ESPN's zeros with NULL for stats that are missing for a whole season.

    Otherwise 2017-18 would show 0 passes per match, and averages across
    seasons would be dragged down by numbers that were never recorded.
    """
    coverage = stat_coverage_by_season(club_match_stats, matches)
    season_of_match = club_match_stats["espn_event_id"].map(matches.set_index("espn_event_id")["season_year"])

    cleaned = club_match_stats.copy()
    for row in missing_stat_seasons(coverage).itertuples():
        cleaned.loc[season_of_match == row.season_year, row.stat] = None
    return cleaned


def run_checks(tables: dict) -> ValidationReport:
    report = ValidationReport()
    check_foreign_keys(tables, report)
    check_duplicates(tables, report)
    check_stats_present(tables, report)
    check_score_consistency(tables, report)
    check_possession_totals(tables, report)
    check_stat_coverage(tables, report)

    for warning in report.warnings:
        log.warning(warning)
    return report
