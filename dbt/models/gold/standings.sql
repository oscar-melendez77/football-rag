-- League table per competition for the current season, computed from results.
-- Tiebreakers: points, goal difference, goals scored (leagues that use head-to-head may differ slightly).

with current_season as (
    select competition_code, max(season_id) as season_id
    from {{ ref('team_match_results') }}
    group by competition_code
),

aggregated as (
    select
        r.competition_code,
        r.season_id,
        r.team_id,
        count(*) as played,
        countif(r.result = 'W') as won,
        countif(r.result = 'D') as drawn,
        countif(r.result = 'L') as lost,
        sum(r.goals_for) as goals_for,
        sum(r.goals_against) as goals_against,
        sum(r.goals_for) - sum(r.goals_against) as goal_difference,
        sum(r.points) as points
    from {{ ref('team_match_results') }} as r
    join current_season as cs
        on cs.competition_code = r.competition_code
        and cs.season_id = r.season_id
    group by r.competition_code, r.season_id, r.team_id
)

select
    concat(a.competition_code, '|', cast(a.team_id as string)) as standings_key,
    a.competition_code,
    a.season_id,
    rank() over (
        partition by a.competition_code
        order by a.points desc, a.goal_difference desc, a.goals_for desc
    ) as position,
    a.team_id,
    t.team_name,
    a.played,
    a.won,
    a.drawn,
    a.lost,
    a.goals_for,
    a.goals_against,
    a.goal_difference,
    a.points
from aggregated as a
left join {{ ref('teams') }} as t on t.team_id = a.team_id