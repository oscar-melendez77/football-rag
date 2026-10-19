-- Recent form per team (last 5 matches across competitions) plus domestic league position.

with ranked as (
    select
        *,
        row_number() over (partition by team_id order by kickoff_utc desc) as recency
    from {{ ref('team_match_results') }}
),

last_five as (
    select
        team_id,
        string_agg(result, '' order by kickoff_utc desc) as form_last5,
        sum(points) as points_last5,
        sum(goals_for) as goals_for_last5,
        sum(goals_against) as goals_against_last5,
        count(*) as matches_in_form,
        max(kickoff_utc) as last_match_at
    from ranked
    where recency <= 5
    group by team_id
),

domestic as (
    select team_id, competition_code, position, points, played
    from {{ ref('standings') }}
    where competition_code != 'CL'
)

select
    t.team_id,
    t.team_name,
    f.form_last5,
    f.points_last5,
    f.goals_for_last5,
    f.goals_against_last5,
    f.matches_in_form,
    f.last_match_at,
    d.competition_code as domestic_competition,
    d.position as domestic_position,
    d.points as domestic_points,
    d.played as domestic_played
from {{ ref('teams') }} as t
left join last_five as f on f.team_id = t.team_id
left join domestic as d on d.team_id = t.team_id