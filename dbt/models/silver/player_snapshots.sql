-- One row per player per FPL snapshot (every 6 hours). Raw history, rebuilt from bronze.

with files as (
    select
        timestamp(json_value(payload, '$.fetched_at')) as snapshot_at,
        payload
    from {{ source('bronze', 'raw_files') }}
    where source = 'fpl'
      and json_value(payload, '$.endpoint') = 'bootstrap-static/'
),

fpl_teams as (
    select
        f.snapshot_at,
        cast(json_value(t, '$.id') as int64) as fpl_team_id,
        json_value(t, '$.name') as team_name,
        json_value(t, '$.short_name') as team_short_name
    from files as f,
        unnest(json_query_array(f.payload, '$.data.teams')) as t
),

players as (
    select f.snapshot_at, p
    from files as f,
        unnest(json_query_array(f.payload, '$.data.elements')) as p
)

select
    concat(json_value(pl.p, '$.id'), '|', cast(pl.snapshot_at as string)) as snapshot_key,
    cast(json_value(pl.p, '$.id') as int64) as player_id,
    pl.snapshot_at,
    json_value(pl.p, '$.web_name') as web_name,
    concat(json_value(pl.p, '$.first_name'), ' ', json_value(pl.p, '$.second_name')) as full_name,
    cast(json_value(pl.p, '$.team') as int64) as fpl_team_id,
    ft.team_name,
    ft.team_short_name,
    case cast(json_value(pl.p, '$.element_type') as int64)
        when 1 then 'GK' when 2 then 'DEF' when 3 then 'MID' when 4 then 'FWD'
    end as position,
    json_value(pl.p, '$.status') as status_code,
    case json_value(pl.p, '$.status')
        when 'a' then 'available'
        when 'd' then 'doubtful'
        when 'i' then 'injured'
        when 's' then 'suspended'
        when 'u' then 'unavailable'
        when 'n' then 'not_in_squad'
    end as status,
    nullif(json_value(pl.p, '$.news'), '') as news,
    safe.timestamp(json_value(pl.p, '$.news_added')) as news_added_at,
    cast(json_value(pl.p, '$.chance_of_playing_next_round') as int64) as chance_next_round,
    safe_cast(json_value(pl.p, '$.form') as float64) as form,
    cast(json_value(pl.p, '$.total_points') as int64) as total_points,
    cast(json_value(pl.p, '$.minutes') as int64) as minutes,
    cast(json_value(pl.p, '$.goals_scored') as int64) as goals,
    cast(json_value(pl.p, '$.assists') as int64) as assists
from players as pl
left join fpl_teams as ft
    on ft.snapshot_at = pl.snapshot_at
    and ft.fpl_team_id = cast(json_value(pl.p, '$.team') as int64)