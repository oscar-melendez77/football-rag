{{ config(severity='warn') }}

-- Premier League teams whose 3-letter code found no FPL squad (e.g. a code mismatch).
select t.team_id, t.team_name, t.tla
from {{ ref('teams') }} as t
where 'PL' in unnest(t.competitions)
  and t.team_id not in (select team_id from {{ ref('team_availability') }})