-- One row per team per finished match: the building block for standings and form.

with finished as (
    select *
    from {{ ref('matches') }}
    where status = 'FINISHED'
      and home_goals is not null
      and away_goals is not null
),

sides as (
    select
        match_id, competition_code, season_id, kickoff_utc,
        home_team_id as team_id, away_team_id as opponent_id, true as is_home,
        home_goals as goals_for, away_goals as goals_against
    from finished
    union all
    select
        match_id, competition_code, season_id, kickoff_utc,
        away_team_id, home_team_id, false,
        away_goals, home_goals
    from finished
)

select
    concat(cast(match_id as string), '|', cast(team_id as string)) as team_match_key,
    *,
    case
        when goals_for > goals_against then 'W'
        when goals_for = goals_against then 'D'
        else 'L'
    end as result,
    case
        when goals_for > goals_against then 3
        when goals_for = goals_against then 1
        else 0
    end as points
from sides