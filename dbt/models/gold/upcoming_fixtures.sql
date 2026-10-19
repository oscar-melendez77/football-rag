-- One row per upcoming match: odds, both teams' form and position, and absences (PL only).
-- Rebuilt on every dbt run, so "upcoming" is relative to the latest build.

with upcoming as (
    select *
    from {{ ref('matches') }}
    where status in ('SCHEDULED', 'TIMED')
      and kickoff_utc >= current_timestamp()
)

select
    u.match_id,
    u.competition_code,
    u.kickoff_utc,
    u.matchday,
    u.home_team_id,
    u.home_team_name,
    u.away_team_id,
    u.away_team_name,
    o.prob_home,
    o.prob_draw,
    o.prob_away,
    o.bookmaker_count,
    case
        when o.match_id is null then null
        when o.prob_home >= o.prob_draw and o.prob_home >= o.prob_away then 'home'
        when o.prob_away >= o.prob_draw then 'away'
        else 'draw'
    end as market_favorite,
    hf.form_last5 as home_form_last5,
    hf.points_last5 as home_points_last5,
    hf.domestic_position as home_position,
    af.form_last5 as away_form_last5,
    af.points_last5 as away_points_last5,
    af.domestic_position as away_position,
    ha.players_out as home_players_out,
    ha.players_doubtful as home_players_doubtful,
    aa.players_out as away_players_out,
    aa.players_doubtful as away_players_doubtful
from upcoming as u
left join {{ ref('odds') }} as o on o.match_id = u.match_id
left join {{ ref('team_form') }} as hf on hf.team_id = u.home_team_id
left join {{ ref('team_form') }} as af on af.team_id = u.away_team_id
left join {{ ref('team_availability') }} as ha on ha.team_id = u.home_team_id
left join {{ ref('team_availability') }} as aa on aa.team_id = u.away_team_id