-- Current absences per Premier League team, linking FPL players to teams via the shared 3-letter code.
-- A reviewed seed maps the few codes that differ between the two sources.

with current_status as (
    select
        team_short_name,
        countif(status in ('injured', 'suspended')) as players_out,
        countif(status = 'doubtful') as players_doubtful,
        count(*) as squad_size
    from {{ ref('player_availability') }}
    where is_current
    group by team_short_name
),

pl_teams as (
    select
        t.team_id,
        t.team_name,
        t.tla,
        coalesce(o.fpl_short_name, t.tla) as fpl_code
    from {{ ref('teams') }} as t
    left join {{ ref('team_code_overrides') }} as o on o.football_data_tla = t.tla
    where 'PL' in unnest(t.competitions)
)

select
    p.team_id,
    p.team_name,
    p.tla,
    p.fpl_code,
    c.players_out,
    c.players_doubtful,
    c.squad_size
from pl_teams as p
join current_status as c on c.team_short_name = p.fpl_code