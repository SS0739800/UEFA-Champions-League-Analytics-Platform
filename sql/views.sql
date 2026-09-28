-- Views for the questions we ask over and over.
-- Loaded by the ETL right after schema.sql.


-- One row per club per finished match, from that club's point of view.
-- Most other queries start from here instead of joining matches twice.
CREATE VIEW v_club_matches AS
SELECT
    m.match_id,
    s.start_year                           AS season_year,
    s.label                                AS season,
    m.stage,
    m.group_name,
    m.leg,
    m.kickoff_utc,
    side.club_id,
    side.opponent_id,
    side.is_home,
    m.is_neutral_venue,
    side.goals_for,
    side.goals_against,
    side.goals_for_90,
    side.goals_against_90,
    m.went_to_extra_time,
    -- Result on the final score. A knockout game settled on penalties counts as a draw here.
    CASE
        WHEN side.goals_for > side.goals_against THEN 'W'
        WHEN side.goals_for = side.goals_against THEN 'D'
        ELSE 'L'
    END                                    AS result,
    CASE
        WHEN side.goals_for > side.goals_against THEN 3
        WHEN side.goals_for = side.goals_against THEN 1
        ELSE 0
    END                                    AS points,
    -- Includes shootout wins. For a first leg it only means "won this game", not the tie.
    COALESCE(m.winner_club_id = side.club_id, FALSE) AS won_match,
    own.possession_pct,
    own.shots,
    own.shots_on_target,
    own.passes,
    own.passes_completed,
    own.crosses,
    own.long_balls,
    own.tackles,
    own.interceptions,
    own.clearances,
    own.corners,
    own.fouls,
    (
        SELECT COUNT(*) FROM match_events e
        WHERE e.match_id = m.match_id AND e.club_id = side.club_id AND e.event_type = 'penalty_goal'
    )                                      AS penalty_goals,
    opp.shots                              AS shots_against,
    opp.shots_on_target                    AS shots_on_target_against,
    elo.elo_before,
    opp_elo.elo_before                     AS opponent_elo_before
FROM matches m
JOIN seasons s ON s.season_id = m.season_id
CROSS JOIN LATERAL (
    VALUES
        (m.home_club_id, m.away_club_id, TRUE,  m.home_goals, m.away_goals, m.home_goals_90, m.away_goals_90),
        (m.away_club_id, m.home_club_id, FALSE, m.away_goals, m.home_goals, m.away_goals_90, m.home_goals_90)
) AS side (club_id, opponent_id, is_home, goals_for, goals_against, goals_for_90, goals_against_90)
LEFT JOIN club_match_stats own ON own.match_id = m.match_id AND own.club_id = side.club_id
LEFT JOIN club_match_stats opp ON opp.match_id = m.match_id AND opp.club_id = side.opponent_id
LEFT JOIN club_elo elo         ON elo.match_id = m.match_id AND elo.club_id = side.club_id
LEFT JOIN club_elo opp_elo     ON opp_elo.match_id = m.match_id AND opp_elo.club_id = side.opponent_id
WHERE m.status = 'finished';


-- Group stage / league phase table, worked out from results.
-- Ties are split on goal difference, then goals scored. UEFA's real
-- tiebreakers (head-to-head for groups) aren't applied, so a tied position
-- can differ from the official table.
CREATE VIEW v_group_standings AS
WITH totals AS (
    SELECT
        season_year,
        season,
        stage,
        group_name,
        club_id,
        COUNT(*)                                  AS played,
        COUNT(*) FILTER (WHERE result = 'W')      AS wins,
        COUNT(*) FILTER (WHERE result = 'D')      AS draws,
        COUNT(*) FILTER (WHERE result = 'L')      AS losses,
        SUM(goals_for)                            AS goals_for,
        SUM(goals_against)                        AS goals_against,
        SUM(goals_for - goals_against)            AS goal_difference,
        SUM(points)                               AS points
    FROM v_club_matches
    WHERE stage IN ('group_stage', 'league_phase')
    GROUP BY season_year, season, stage, group_name, club_id
)
SELECT
    t.*,
    RANK() OVER (
        PARTITION BY season_year, group_name
        ORDER BY points DESC, goal_difference DESC, goals_for DESC
    ) AS position
FROM totals t;


-- Season totals for every club.
CREATE VIEW v_club_season_stats AS
WITH stage_rank AS (
    SELECT
        cm.*,
        CASE stage
            WHEN 'group_stage'      THEN 1
            WHEN 'league_phase'     THEN 1
            WHEN 'knockout_playoff' THEN 2
            WHEN 'round_of_16'      THEN 3
            WHEN 'quarter_final'    THEN 4
            WHEN 'semi_final'       THEN 5
            WHEN 'final'            THEN 6
        END AS stage_order
    FROM v_club_matches cm
)
SELECT
    sr.season_year,
    sr.season,
    sr.club_id,
    c.name                                             AS club_name,
    COUNT(*)                                           AS matches,
    COUNT(*) FILTER (WHERE result = 'W')               AS wins,
    COUNT(*) FILTER (WHERE result = 'D')               AS draws,
    COUNT(*) FILTER (WHERE result = 'L')               AS losses,
    SUM(points)                                        AS points,
    SUM(goals_for)                                     AS goals_for,
    SUM(goals_against)                                 AS goals_against,
    SUM(goals_for) - SUM(goals_against)                AS goal_difference,
    ROUND(SUM(points)::NUMERIC / COUNT(*), 2)          AS points_per_match,
    ROUND(SUM(goals_for)::NUMERIC / COUNT(*), 2)       AS goals_per_match,
    ROUND(SUM(goals_against)::NUMERIC / COUNT(*), 2)   AS goals_against_per_match,
    COUNT(*) FILTER (WHERE goals_against = 0)          AS clean_sheets,
    SUM(shots)                                         AS shots,
    SUM(shots_on_target)                               AS shots_on_target,
    SUM(shots_against)                                 AS shots_against,
    SUM(shots_on_target_against)                       AS shots_on_target_against,
    ROUND(AVG(possession_pct), 1)                      AS avg_possession_pct,
    ROUND(SUM(passes_completed)::NUMERIC / NULLIF(SUM(passes), 0), 3) AS pass_completion,
    SUM(penalty_goals)                                 AS penalty_goals,
    MAX(stage_order)                                   AS furthest_stage_order,
    BOOL_OR(stage = 'final' AND won_match)             AS won_title
FROM stage_rank sr
JOIN clubs c ON c.club_id = sr.club_id
GROUP BY sr.season_year, sr.season, sr.club_id, c.name;


-- Season totals and per-90 rates for every player at every club.
-- A player who moved clubs mid-season gets one row per club.
--
-- Penalties come from match_events. We assume ESPN counts a penalty as a shot
-- (and a scored or saved one as on target), so the non-penalty columns take
-- them back out.
CREATE VIEW v_player_season_stats AS
WITH penalties AS (
    SELECT
        m.season_id,
        e.player_id,
        e.club_id,
        COUNT(*) FILTER (WHERE e.event_type = 'penalty_goal')                      AS penalty_goals,
        COUNT(*)                                                                   AS penalty_attempts,
        COUNT(*) FILTER (WHERE e.event_type IN ('penalty_goal', 'penalty_saved'))  AS penalties_on_target
    FROM match_events e
    JOIN matches m ON m.match_id = e.match_id
    WHERE e.event_type IN ('penalty_goal', 'penalty_saved', 'penalty_missed')
    GROUP BY m.season_id, e.player_id, e.club_id
),
totals AS (
    SELECT
        m.season_id,
        pms.player_id,
        pms.club_id,
        MODE() WITHIN GROUP (ORDER BY pms.position_group)    AS position_group,
        COUNT(*)                                             AS appearances,
        COUNT(*) FILTER (WHERE pms.is_starter)               AS starts,
        SUM(pms.minutes_played)                              AS minutes,
        SUM(pms.goals)                                       AS goals,
        SUM(pms.assists)                                     AS assists,
        SUM(pms.shots)                                       AS shots,
        SUM(pms.shots_on_target)                             AS shots_on_target,
        SUM(pms.fouls_committed)                             AS fouls_committed,
        SUM(pms.fouls_suffered)                              AS fouls_suffered,
        SUM(pms.yellow_cards)                                AS yellow_cards,
        SUM(pms.red_cards)                                   AS red_cards,
        SUM(pms.saves)                                       AS saves,
        SUM(pms.goals_conceded)                              AS goals_conceded,
        SUM(pms.shots_faced)                                 AS shots_faced
    FROM player_match_stats pms
    JOIN matches m ON m.match_id = pms.match_id
    GROUP BY m.season_id, pms.player_id, pms.club_id
),
combined AS (
    SELECT
        t.*,
        COALESCE(pen.penalty_goals, 0)                               AS penalty_goals,
        COALESCE(pen.penalty_attempts, 0)                            AS penalty_attempts,
        t.goals - COALESCE(pen.penalty_goals, 0)                     AS non_penalty_goals,
        -- A handful of penalties aren't counted as shots by ESPN, which would
        -- leave -1 here. Floor at zero rather than show a negative count.
        GREATEST(t.shots - COALESCE(pen.penalty_attempts, 0), 0)                AS non_penalty_shots,
        GREATEST(t.shots_on_target - COALESCE(pen.penalties_on_target, 0), 0)   AS non_penalty_shots_on_target
    FROM totals t
    LEFT JOIN penalties pen
        ON pen.season_id = t.season_id AND pen.player_id = t.player_id AND pen.club_id = t.club_id
)
SELECT
    s.start_year                                          AS season_year,
    s.label                                               AS season,
    cb.player_id,
    p.full_name                                           AS player_name,
    cb.club_id,
    c.name                                                AS club_name,
    cb.position_group,
    cb.appearances,
    cb.starts,
    cb.minutes,
    cb.goals,
    cb.assists,
    cb.shots,
    cb.shots_on_target,
    cb.penalty_goals,
    cb.penalty_attempts,
    cb.non_penalty_goals,
    cb.non_penalty_shots,
    cb.non_penalty_shots_on_target,
    cb.fouls_committed,
    cb.fouls_suffered,
    cb.yellow_cards,
    cb.red_cards,
    cb.saves,
    cb.goals_conceded,
    cb.shots_faced,
    -- NULLIF keeps players with 0 minutes from dividing by zero; their rates come out NULL.
    ROUND(cb.goals * 90.0 / NULLIF(cb.minutes, 0), 3)                          AS goals_per90,
    ROUND(cb.non_penalty_goals * 90.0 / NULLIF(cb.minutes, 0), 3)              AS non_penalty_goals_per90,
    ROUND(cb.assists * 90.0 / NULLIF(cb.minutes, 0), 3)                        AS assists_per90,
    ROUND((cb.goals + cb.assists) * 90.0 / NULLIF(cb.minutes, 0), 3)           AS goal_contributions_per90,
    ROUND(cb.shots * 90.0 / NULLIF(cb.minutes, 0), 3)                          AS shots_per90,
    ROUND(cb.shots_on_target * 90.0 / NULLIF(cb.minutes, 0), 3)                AS shots_on_target_per90,
    ROUND(cb.goals::NUMERIC / NULLIF(cb.shots, 0), 3)                          AS shot_conversion,
    ROUND(cb.shots_on_target::NUMERIC / NULLIF(cb.shots, 0), 3)                AS shot_accuracy,
    ROUND(cb.saves::NUMERIC / NULLIF(cb.saves + cb.goals_conceded, 0), 3)      AS save_pct
FROM combined cb
JOIN seasons s ON s.season_id = cb.season_id
JOIN players p ON p.player_id = cb.player_id
JOIN clubs c   ON c.club_id = cb.club_id;
