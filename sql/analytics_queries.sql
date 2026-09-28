-- Analytical queries used by the dashboard and notebooks.
--
-- Each query starts with a "-- name:" line so src/database/queries.py can load
-- it by name. Parameters use :name syntax (SQLAlchemy text()).
-- Most take :season_year, the year the season starts (2024 = 2024-25).


-- name: highest_scoring_clubs
-- Which clubs score the most per game this season?
SELECT
    club_name,
    matches,
    goals_for,
    goals_per_match,
    shots_on_target,
    ROUND(shots_on_target::NUMERIC / matches, 2) AS shots_on_target_per_match
FROM v_club_season_stats
WHERE season_year = :season_year
ORDER BY goals_per_match DESC, goals_for DESC
LIMIT :limit;


-- name: best_defensive_clubs
-- Which clubs concede the least, and do they also limit shots on target?
-- Clubs with fewer than 4 games are left out; one clean sheet shouldn't top the list.
SELECT
    club_name,
    matches,
    goals_against,
    goals_against_per_match,
    clean_sheets,
    ROUND(clean_sheets::NUMERIC / matches, 3)                    AS clean_sheet_rate,
    ROUND(shots_on_target_against::NUMERIC / matches, 2)         AS shots_on_target_against_per_match
FROM v_club_season_stats
WHERE season_year = :season_year
  AND matches >= 4
ORDER BY goals_against_per_match, shots_on_target_against_per_match;


-- name: shot_volume_leaders
-- Who takes the most shots, and how many of them hit the target?
SELECT
    club_name,
    matches,
    ROUND(shots::NUMERIC / matches, 1)                           AS shots_per_match,
    ROUND(shots_on_target::NUMERIC / matches, 1)                 AS shots_on_target_per_match,
    ROUND(shots_on_target::NUMERIC / NULLIF(shots, 0), 3)        AS shot_accuracy
FROM v_club_season_stats
WHERE season_year = :season_year
ORDER BY shots_per_match DESC;


-- name: shots_on_target_difference
-- Our closest thing to xG difference: shots on target for minus against, per match.
-- It rewards clubs that create more good chances than they allow, but ignores shot quality.
SELECT
    club_name,
    matches,
    ROUND((shots_on_target - shots_on_target_against)::NUMERIC / matches, 2) AS sot_difference_per_match,
    ROUND(goal_difference::NUMERIC / matches, 2)                            AS goal_difference_per_match,
    RANK() OVER (ORDER BY (shots_on_target - shots_on_target_against)::NUMERIC / matches DESC) AS sot_rank,
    RANK() OVER (ORDER BY goal_difference::NUMERIC / matches DESC)                          AS goal_diff_rank
FROM v_club_season_stats
WHERE season_year = :season_year
ORDER BY sot_difference_per_match DESC;


-- name: club_shot_conversion
-- How often do clubs turn shots into goals? Needs at least 30 shots to be listed.
SELECT
    club_name,
    shots,
    shots_on_target,
    goals_for,
    ROUND(goals_for::NUMERIC / NULLIF(shots, 0), 3)              AS goals_per_shot,
    ROUND(goals_for::NUMERIC / NULLIF(shots_on_target, 0), 3)    AS goals_per_shot_on_target
FROM v_club_season_stats
WHERE season_year = :season_year
  AND shots >= 30
ORDER BY goals_per_shot DESC;


-- name: home_away_split
-- Points per match at home and away. Neutral venues (finals, Lisbon 2020) are left out.
SELECT
    c.name                                                                    AS club_name,
    COUNT(*) FILTER (WHERE cm.is_home)                                        AS home_matches,
    ROUND(AVG(cm.points) FILTER (WHERE cm.is_home), 2)                        AS home_points_per_match,
    COUNT(*) FILTER (WHERE NOT cm.is_home)                                    AS away_matches,
    ROUND(AVG(cm.points) FILTER (WHERE NOT cm.is_home), 2)                    AS away_points_per_match,
    ROUND(AVG(cm.points) FILTER (WHERE cm.is_home)
        - AVG(cm.points) FILTER (WHERE NOT cm.is_home), 2)                    AS home_minus_away
FROM v_club_matches cm
JOIN clubs c ON c.club_id = cm.club_id
WHERE cm.season_year = :season_year
  AND NOT cm.is_neutral_venue
GROUP BY c.name
ORDER BY home_minus_away DESC NULLS LAST;


-- name: home_advantage_by_season
-- How big is home advantage, and did it disappear in the closed-door 2020-21 season?
-- Each match is counted once, from the home side.
SELECT
    season,
    COUNT(*)                                                        AS matches,
    ROUND(AVG((goals_for > goals_against)::INT), 3)                 AS home_win_rate,
    ROUND(AVG((goals_for = goals_against)::INT), 3)                 AS draw_rate,
    ROUND(AVG((goals_for < goals_against)::INT), 3)                 AS away_win_rate,
    ROUND(AVG(goals_for - goals_against), 2)                        AS home_goal_margin
FROM v_club_matches
WHERE is_home AND NOT is_neutral_venue
GROUP BY season_year, season
ORDER BY season_year;


-- name: recent_form
-- Each club's last five results this season, newest first.
WITH ranked AS (
    SELECT
        cm.*,
        ROW_NUMBER() OVER (PARTITION BY cm.club_id ORDER BY cm.kickoff_utc DESC) AS recency
    FROM v_club_matches cm
    WHERE cm.season_year = :season_year
)
SELECT
    c.name                                                      AS club_name,
    STRING_AGG(r.result, '' ORDER BY r.kickoff_utc DESC)        AS last_five,
    SUM(r.points)                                               AS points,
    SUM(r.goals_for - r.goals_against)                          AS goal_difference
FROM ranked r
JOIN clubs c ON c.club_id = r.club_id
WHERE r.recency <= 5
GROUP BY c.name
ORDER BY points DESC, goal_difference DESC;


-- name: clean_sheet_leaders_all_time
-- Most clean sheets across every season we have.
SELECT
    c.name                                              AS club_name,
    COUNT(*)                                            AS matches,
    COUNT(*) FILTER (WHERE cm.goals_against = 0)        AS clean_sheets,
    ROUND(AVG((cm.goals_against = 0)::INT), 3)          AS clean_sheet_rate
FROM v_club_matches cm
JOIN clubs c ON c.club_id = cm.club_id
GROUP BY c.name
HAVING COUNT(*) >= 30
ORDER BY clean_sheets DESC
LIMIT :limit;


-- name: top_scorers_per90
-- Goals per 90 for players over a minutes threshold, with non-penalty goals alongside.
SELECT
    player_name,
    club_name,
    position_group,
    minutes,
    goals,
    penalty_goals,
    goals_per90,
    non_penalty_goals_per90
FROM v_player_season_stats
WHERE season_year = :season_year
  AND minutes >= :min_minutes
ORDER BY goals_per90 DESC, goals DESC
LIMIT :limit;


-- name: top_assisters_per90
SELECT
    player_name,
    club_name,
    position_group,
    minutes,
    assists,
    assists_per90,
    goal_contributions_per90
FROM v_player_season_stats
WHERE season_year = :season_year
  AND minutes >= :min_minutes
ORDER BY assists_per90 DESC, assists DESC
LIMIT :limit;


-- name: finishing_vs_average
-- Non-penalty goals compared with what an average finisher would score from the
-- same shots on target. Not xG: it knows nothing about where the shots came from.
WITH season_rate AS (
    SELECT
        SUM(non_penalty_goals)::NUMERIC / NULLIF(SUM(non_penalty_shots_on_target), 0) AS goals_per_sot
    FROM v_player_season_stats
    WHERE season_year = :season_year
)
SELECT
    p.player_name,
    p.club_name,
    p.non_penalty_shots,
    p.non_penalty_shots_on_target,
    p.non_penalty_goals,
    ROUND(p.non_penalty_shots_on_target * sr.goals_per_sot, 2)                       AS average_conversion_goals,
    ROUND(p.non_penalty_goals - p.non_penalty_shots_on_target * sr.goals_per_sot, 2) AS goals_above_average
FROM v_player_season_stats p
CROSS JOIN season_rate sr
WHERE p.season_year = :season_year
  AND p.non_penalty_shots >= :min_shots
ORDER BY goals_above_average DESC;


-- name: player_comparison
-- Side-by-side season numbers for a chosen set of players.
SELECT
    player_name,
    club_name,
    season,
    appearances,
    minutes,
    goals,
    assists,
    goals_per90,
    assists_per90,
    shots_per90,
    shot_accuracy,
    shot_conversion
FROM v_player_season_stats
WHERE player_id = ANY(:player_ids)
  AND season_year = :season_year
ORDER BY goals_per90 DESC;


-- name: season_over_season_change
-- How each club's points and goal difference per match changed from its previous UCL season.
-- LAG looks at the club's last season *in the competition*, which isn't always the year before.
WITH per_season AS (
    SELECT
        club_id,
        club_name,
        season_year,
        season,
        points_per_match,
        ROUND(goal_difference::NUMERIC / matches, 2) AS goal_diff_per_match
    FROM v_club_season_stats
),
with_previous AS (
    SELECT
        ps.*,
        LAG(season_year)          OVER w AS previous_season_year,
        LAG(points_per_match)     OVER w AS previous_points_per_match,
        LAG(goal_diff_per_match)  OVER w AS previous_goal_diff_per_match
    FROM per_season ps
    WINDOW w AS (PARTITION BY club_id ORDER BY season_year)
)
SELECT
    club_name,
    season,
    previous_season_year,
    previous_points_per_match,
    points_per_match,
    points_per_match - previous_points_per_match           AS points_per_match_change,
    goal_diff_per_match - previous_goal_diff_per_match     AS goal_diff_per_match_change
FROM with_previous
WHERE season_year = :season_year
  AND previous_season_year IS NOT NULL
ORDER BY points_per_match_change DESC;


-- name: club_consistency
-- How much a club's goal difference swings from game to game across all seasons.
-- A low standard deviation means results are predictable, not necessarily good.
SELECT
    c.name                                                AS club_name,
    COUNT(*)                                              AS matches,
    ROUND(AVG(cm.goals_for - cm.goals_against), 2)        AS avg_goal_difference,
    ROUND(STDDEV_SAMP(cm.goals_for - cm.goals_against), 2) AS goal_difference_std,
    ROUND(STDDEV_SAMP(cm.points), 2)                      AS points_std
FROM v_club_matches cm
JOIN clubs c ON c.club_id = cm.club_id
GROUP BY c.name
HAVING COUNT(*) >= 40
ORDER BY goal_difference_std;


-- name: results_vs_elo_expectation
-- Opponent-adjusted performance: how many more "points" a club took than Elo expected
-- before each game. Scores are 1 for a win, 0.5 for a draw, 0 for a loss.
-- Home advantage is 60 Elo points (same as src/features/elo.py), except at neutral venues.
WITH scored AS (
    SELECT
        cm.club_id,
        CASE cm.result WHEN 'W' THEN 1.0 WHEN 'D' THEN 0.5 ELSE 0.0 END AS actual,
        1.0 / (1.0 + POWER(10, -(
            cm.elo_before - cm.opponent_elo_before
            + CASE WHEN cm.is_neutral_venue THEN 0 WHEN cm.is_home THEN 60 ELSE -60 END
        ) / 400.0)) AS expected
    FROM v_club_matches cm
    WHERE cm.season_year = :season_year
)
SELECT
    c.name                                      AS club_name,
    COUNT(*)                                    AS matches,
    ROUND(SUM(actual), 1)                       AS actual_score,
    ROUND(SUM(expected), 2)                     AS elo_expected_score,
    ROUND(SUM(actual - expected), 2)            AS score_above_expected
FROM scored s
JOIN clubs c ON c.club_id = s.club_id
GROUP BY c.name
ORDER BY score_above_expected DESC;


-- name: close_match_record
-- Results in tight games: draws and one-goal games. These are the least predictable.
SELECT
    c.name                                                  AS club_name,
    COUNT(*)                                                AS close_matches,
    COUNT(*) FILTER (WHERE cm.result = 'W')                 AS wins,
    COUNT(*) FILTER (WHERE cm.result = 'D')                 AS draws,
    COUNT(*) FILTER (WHERE cm.result = 'L')                 AS losses,
    ROUND(AVG(cm.points), 2)                                AS points_per_close_match
FROM v_club_matches cm
JOIN clubs c ON c.club_id = cm.club_id
WHERE ABS(cm.goals_for - cm.goals_against) <= 1
  AND cm.season_year >= :from_season
GROUP BY c.name
HAVING COUNT(*) >= 10
ORDER BY points_per_close_match DESC;


-- name: rolling_goal_difference
-- Five-match rolling goal difference and shots-on-target difference for one club,
-- across every season. The window only looks backwards.
SELECT
    cm.season,
    cm.kickoff_utc,
    opp.name                                                                 AS opponent,
    cm.is_home,
    cm.goals_for,
    cm.goals_against,
    ROUND(AVG(cm.goals_for - cm.goals_against) OVER last_five, 2)            AS rolling_goal_difference,
    ROUND(AVG(cm.shots_on_target - cm.shots_on_target_against) OVER last_five, 2) AS rolling_sot_difference
FROM v_club_matches cm
JOIN clubs opp ON opp.club_id = cm.opponent_id
WHERE cm.club_id = :club_id
WINDOW last_five AS (ORDER BY cm.kickoff_utc ROWS BETWEEN 4 PRECEDING AND CURRENT ROW)
ORDER BY cm.kickoff_utc;


-- name: goals_by_match_period
-- When are goals scored? 15-minute buckets, with added time kept in the bucket it
-- belongs to (a 45+2 goal is first half, a 90+4 goal is last 15 minutes).
SELECT
    CASE
        WHEN period = 1 AND minute <= 15 THEN '01-15'
        WHEN period = 1 AND minute <= 30 THEN '16-30'
        WHEN period = 1                  THEN '31-45+'
        WHEN period = 2 AND minute <= 60 THEN '46-60'
        WHEN period = 2 AND minute <= 75 THEN '61-75'
        WHEN period = 2                  THEN '76-90+'
        ELSE 'Extra time'
    END                              AS match_period,
    COUNT(*)                         AS goals,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) AS share_pct
FROM match_events e
JOIN matches m ON m.match_id = e.match_id
JOIN seasons s ON s.season_id = m.season_id
WHERE e.event_type IN ('goal', 'penalty_goal', 'own_goal')
  AND s.start_year BETWEEN :from_season AND :to_season
GROUP BY match_period
ORDER BY match_period;


-- name: season_trends
-- Competition-wide averages per season, for the history charts.
-- Possession isn't here: across all teams it always averages 50%.
SELECT
    m.season_year,
    m.season,
    COUNT(*) / 2                                                     AS matches,
    ROUND(AVG(m.goals_for) * 2, 2)                                   AS goals_per_match,
    ROUND(AVG(m.shots) * 2, 1)                                       AS shots_per_match,
    ROUND(AVG(m.shots_on_target) * 2, 1)                             AS shots_on_target_per_match,
    ROUND(SUM(m.goals_for)::NUMERIC / NULLIF(SUM(m.shots), 0), 3)    AS goals_per_shot,
    ROUND(AVG(m.passes) * 2, 0)                                      AS passes_per_match,
    ROUND(SUM(m.passes_completed)::NUMERIC / NULLIF(SUM(m.passes), 0), 3) AS pass_completion,
    ROUND(STDDEV_SAMP(m.possession_pct), 1)                          AS possession_spread
FROM v_club_matches m
GROUP BY m.season_year, m.season
ORDER BY m.season_year;


-- name: comeback_wins
-- Matches a club won after being behind at some point. Uses a running score built
-- from goal events in order, so it needs the key events for the match.
WITH goals AS (
    SELECT
        e.match_id,
        e.club_id,
        e.period,
        e.minute,
        e.added_time,
        e.event_id
    FROM match_events e
    WHERE e.event_type IN ('goal', 'penalty_goal', 'own_goal')
),
running AS (
    SELECT
        g.match_id,
        m.home_club_id,
        m.away_club_id,
        SUM((g.club_id = m.home_club_id)::INT) OVER w - SUM((g.club_id = m.away_club_id)::INT) OVER w AS home_lead
    FROM goals g
    JOIN matches m ON m.match_id = g.match_id
    WINDOW w AS (PARTITION BY g.match_id ORDER BY g.period, g.minute, g.added_time, g.event_id)
),
worst_deficit AS (
    SELECT match_id, home_club_id, away_club_id, MIN(home_lead) AS lowest_home_lead, MAX(home_lead) AS highest_home_lead
    FROM running
    GROUP BY match_id, home_club_id, away_club_id
)
SELECT
    s.label                                   AS season,
    m.kickoff_utc::DATE                       AS match_date,
    winner.name                               AS winner,
    loser.name                                AS loser,
    m.home_goals || '-' || m.away_goals       AS final_score,
    CASE WHEN m.home_goals > m.away_goals THEN -wd.lowest_home_lead ELSE wd.highest_home_lead END AS biggest_deficit
FROM worst_deficit wd
JOIN matches m ON m.match_id = wd.match_id
JOIN seasons s ON s.season_id = m.season_id
JOIN clubs winner ON winner.club_id = CASE WHEN m.home_goals > m.away_goals THEN m.home_club_id ELSE m.away_club_id END
JOIN clubs loser  ON loser.club_id  = CASE WHEN m.home_goals > m.away_goals THEN m.away_club_id ELSE m.home_club_id END
WHERE (m.home_goals > m.away_goals AND wd.lowest_home_lead < 0)
   OR (m.away_goals > m.home_goals AND wd.highest_home_lead > 0)
ORDER BY biggest_deficit DESC, m.kickoff_utc DESC;


-- name: knockout_appearances
-- How often each club has reached each knockout stage across all seasons we have.
SELECT
    club_name,
    COUNT(*)                                             AS seasons,
    COUNT(*) FILTER (WHERE furthest_stage_order >= 3)    AS reached_round_of_16,
    COUNT(*) FILTER (WHERE furthest_stage_order >= 4)    AS reached_quarter_finals,
    COUNT(*) FILTER (WHERE furthest_stage_order >= 5)    AS reached_semi_finals,
    COUNT(*) FILTER (WHERE furthest_stage_order >= 6)    AS reached_final,
    COUNT(*) FILTER (WHERE won_title)                    AS titles
FROM v_club_season_stats
WHERE season_year < :current_season
GROUP BY club_name
HAVING COUNT(*) FILTER (WHERE furthest_stage_order >= 4) > 0
ORDER BY reached_semi_finals DESC, reached_quarter_finals DESC, titles DESC;


-- name: biggest_elo_risers
-- Clubs whose UCL Elo rating rose the most over a season (first game to last game).
-- ESPN has no progressive passing data, so "progress" here means results against expectation.
WITH first_last AS (
    SELECT
        e.club_id,
        FIRST_VALUE(e.elo_before) OVER w  AS season_start,
        LAST_VALUE(e.elo_after)   OVER w  AS season_end,
        ROW_NUMBER() OVER (PARTITION BY e.club_id ORDER BY m.kickoff_utc) AS rn
    FROM club_elo e
    JOIN matches m ON m.match_id = e.match_id
    JOIN seasons s ON s.season_id = m.season_id
    WHERE s.start_year = :season_year
      AND m.status = 'finished'
    WINDOW w AS (
        PARTITION BY e.club_id ORDER BY m.kickoff_utc
        ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
    )
)
SELECT
    c.name                                   AS club_name,
    ROUND(fl.season_start, 0)                AS elo_at_start,
    ROUND(fl.season_end, 0)                  AS elo_at_end,
    ROUND(fl.season_end - fl.season_start, 0) AS elo_change
FROM first_last fl
JOIN clubs c ON c.club_id = fl.club_id
WHERE fl.rn = 1
ORDER BY elo_change DESC;


-- name: penalty_record
-- Penalties taken, scored, saved and missed by club, across all seasons.
SELECT
    c.name                                                           AS club_name,
    COUNT(*)                                                         AS penalties,
    COUNT(*) FILTER (WHERE e.event_type = 'penalty_goal')            AS scored,
    COUNT(*) FILTER (WHERE e.event_type = 'penalty_saved')           AS saved,
    COUNT(*) FILTER (WHERE e.event_type = 'penalty_missed')          AS missed,
    ROUND(AVG((e.event_type = 'penalty_goal')::INT), 3)              AS conversion_rate
FROM match_events e
JOIN clubs c ON c.club_id = e.club_id
WHERE e.event_type IN ('penalty_goal', 'penalty_saved', 'penalty_missed')
GROUP BY c.name
HAVING COUNT(*) >= 5
ORDER BY penalties DESC;
