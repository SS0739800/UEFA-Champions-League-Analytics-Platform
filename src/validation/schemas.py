"""
Column-level rules for each table, checked with Pandera before anything is loaded.

These catch things like negative counts, impossible percentages and unknown
categories. Rules that need more than one table live in checks.py.
"""

import pandera.pandas as pa
from pandera.pandas import Check, Column, DataFrameSchema

from src.etl.transform import EVENT_TYPES, STAGE_ORDER

non_negative = Check.ge(0)
count = Column("float64", non_negative, nullable=True)

matches_schema = DataFrameSchema(
    {
        "espn_event_id": Column(int, unique=True),
        "season_year": Column(int, Check.in_range(2012, 2030)),
        "stage": Column(str, Check.isin(STAGE_ORDER)),
        "group_name": Column(str, Check.isin(list("ABCDEFGH")), nullable=True),
        "leg": Column("float64", Check.isin([1, 2]), nullable=True),
        "status": Column(str, Check.isin(["scheduled", "finished"])),
        "home_espn_id": Column(int),
        "away_espn_id": Column(int),
        # Double figures in a single UCL match has never happened, so treat it as a parsing bug.
        "home_goals": Column("float64", Check.in_range(0, 12), nullable=True),
        "away_goals": Column("float64", Check.in_range(0, 12), nullable=True),
        "home_goals_90": Column("float64", Check.in_range(0, 12), nullable=True),
        "away_goals_90": Column("float64", Check.in_range(0, 12), nullable=True),
        "went_to_extra_time": Column(bool),
        "is_neutral_venue": Column(bool),
        "attendance": Column("float64", Check.in_range(1, 120_000), nullable=True),
    },
    checks=[
        Check(lambda df: df["home_espn_id"] != df["away_espn_id"], error="a club can't play itself"),
        Check(
            lambda df: (df["status"] == "scheduled") | df["home_goals"].notna(),
            error="finished match without a score",
        ),
        Check(
            lambda df: (df["status"] == "finished") | df["home_goals"].isna(),
            error="scheduled match already has a score",
        ),
        Check(
            lambda df: (df["stage"] != "group_stage") | df["group_name"].notna(),
            error="group stage match without a group",
        ),
        # A season starting in year Y runs from roughly August Y to the next summer.
        # 2019-20 finished in late August 2020, so allow up to the end of August.
        Check(
            lambda df: (df["kickoff_utc"].dt.year * 12 + df["kickoff_utc"].dt.month).between(
                df["season_year"] * 12 + 7, (df["season_year"] + 1) * 12 + 8
            ),
            error="kickoff date is outside the season",
        ),
    ],
    strict=False,
)

clubs_schema = DataFrameSchema(
    {
        "espn_team_id": Column(int, unique=True),
        "name": Column(str, Check.str_length(min_value=2)),
        "short_name": Column(str, Check.str_length(min_value=2)),
    },
    strict=False,
)

players_schema = DataFrameSchema(
    {
        "espn_athlete_id": Column(int, unique=True),
        "full_name": Column(str, Check.str_length(min_value=2)),
    },
    strict=False,
)

club_match_stats_schema = DataFrameSchema(
    {
        "espn_event_id": Column(int),
        "espn_team_id": Column(int),
        "possession_pct": Column("float64", Check.in_range(0, 100), nullable=True),
        "shots": count,
        "shots_on_target": count,
        "blocked_shots": count,
        "passes": count,
        "passes_completed": count,
        "crosses": count,
        "crosses_completed": count,
        "long_balls": count,
        "long_balls_completed": count,
        "tackles": count,
        "tackles_won": count,
        "interceptions": count,
        "clearances": count,
        "corners": count,
        "fouls": count,
        "offsides": count,
        "yellow_cards": count,
        "red_cards": Column("float64", Check.in_range(0, 5), nullable=True),
        "saves": count,
    },
    checks=[
        Check(lambda df: ~(df["shots_on_target"] > df["shots"]), error="more shots on target than shots"),
        Check(lambda df: ~(df["passes_completed"] > df["passes"]), error="more completed passes than passes"),
        Check(lambda df: ~(df["crosses_completed"] > df["crosses"]), error="more completed crosses than crosses"),
        Check(
            lambda df: ~(df["long_balls_completed"] > df["long_balls"]),
            error="more completed long balls than long balls",
        ),
    ],
    unique=["espn_event_id", "espn_team_id"],
    strict=False,
)

_player_count = Column(int, non_negative)

player_match_stats_schema = DataFrameSchema(
    {
        "espn_event_id": Column(int),
        "espn_athlete_id": Column(int),
        "espn_team_id": Column(int),
        "position_group": Column(str, Check.isin(["GK", "DEF", "MID", "FWD", "UNK"])),
        "is_starter": Column(bool),
        "minute_on": Column(int, Check.in_range(0, 120)),
        "minute_off": Column(int, Check.in_range(0, 120)),
        "minutes_played": Column(int, Check.in_range(0, 120)),
        "goals": Column(int, Check.in_range(0, 5)),
        "assists": _player_count,
        "shots": _player_count,
        "shots_on_target": _player_count,
        "fouls_committed": _player_count,
        "fouls_suffered": _player_count,
        "offsides": _player_count,
        "yellow_cards": Column(int, Check.in_range(0, 2)),
        "red_cards": Column(int, Check.in_range(0, 1)),
        "own_goals": _player_count,
        "saves": _player_count,
        "goals_conceded": _player_count,
        "shots_faced": _player_count,
    },
    checks=[
        Check(lambda df: df["minute_off"] >= df["minute_on"], error="player went off before coming on"),
        Check(lambda df: df["minutes_played"] == df["minute_off"] - df["minute_on"], error="minutes don't add up"),
        Check(lambda df: df["shots_on_target"] <= df["shots"], error="more shots on target than shots"),
        Check(lambda df: df["is_starter"] == (df["minute_on"] == 0), error="starter who didn't start at minute 0"),
    ],
    unique=["espn_event_id", "espn_athlete_id"],
    strict=False,
)

match_events_schema = DataFrameSchema(
    {
        "espn_event_id": Column(int),
        "espn_play_id": Column(int),
        "event_type": Column(str, Check.isin(sorted(set(EVENT_TYPES.values())))),
        "period": Column(int, Check.in_range(1, 4)),
        "minute": Column(int, Check.in_range(0, 130)),
        "added_time": Column(int, Check.in_range(0, 30)),
    },
    unique=["espn_event_id", "espn_play_id"],
    strict=False,
)

SCHEMAS = {
    "matches": matches_schema,
    "clubs": clubs_schema,
    "players": players_schema,
    "club_match_stats": club_match_stats_schema,
    "player_match_stats": player_match_stats_schema,
    "match_events": match_events_schema,
}


def summarize_failures(failure_cases, frame) -> str:
    """One line per broken rule, with how many rows break it and a few example ids."""
    id_column = "espn_event_id" if "espn_event_id" in frame.columns else frame.columns[0]
    lines = []
    for (column, check), cases in failure_cases.groupby(["column", "check"], dropna=False):
        rows = cases["index"].dropna().unique()
        examples = frame.loc[frame.index.intersection(rows), id_column].head(5).tolist()
        where = f"column '{column}'" if isinstance(column, str) else "row check"
        lines.append(f"{where}: {check} failed for {len(rows)} rows (e.g. {id_column} {examples})")
    return "\n".join(lines)


def validate_tables(tables: dict) -> None:
    """Run every schema. Pandera's lazy mode reports all problems at once instead of the first."""
    for name, schema in SCHEMAS.items():
        # An update with no newly finished matches has empty detail tables. Nothing to check there.
        if tables[name].empty:
            continue
        try:
            schema.validate(tables[name], lazy=True)
        except pa.errors.SchemaErrors as error:
            summary = summarize_failures(error.failure_cases, tables[name])
            raise ValueError(f"Validation failed for table '{name}':\n{summary}") from None
