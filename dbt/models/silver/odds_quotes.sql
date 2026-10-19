-- One row per event per bookmaker per snapshot, with home/draw/away decimal prices.

with events as (
    select
        timestamp(json_value(payload, '$.fetched_at')) as fetched_at,
        json_value(payload, '$.sport_key') as sport_key,
        e
    from {{ source('bronze', 'raw_files') }},
        unnest(json_query_array(payload, '$.events')) as e
    where source = 'odds'
),

outcomes as (
    select
        ev.fetched_at,
        ev.sport_key,
        json_value(ev.e, '$.id') as event_id,
        timestamp(json_value(ev.e, '$.commence_time')) as commence_time,
        json_value(ev.e, '$.home_team') as home_team,
        json_value(ev.e, '$.away_team') as away_team,
        json_value(b, '$.key') as bookmaker,
        json_value(m, '$.key') as market,
        json_value(o, '$.name') as outcome_name,
        cast(json_value(o, '$.price') as float64) as price
    from events as ev,
        unnest(json_query_array(ev.e, '$.bookmakers')) as b,
        unnest(json_query_array(b, '$.markets')) as m,
        unnest(json_query_array(m, '$.outcomes')) as o
)

select
    concat(event_id, '|', bookmaker, '|', cast(fetched_at as string)) as quote_key,
    event_id,
    sport_key,
    commence_time,
    home_team,
    away_team,
    bookmaker,
    fetched_at,
    max(if(outcome_name = home_team, price, null)) as home_price,
    max(if(outcome_name = 'Draw', price, null)) as draw_price,
    max(if(outcome_name = away_team, price, null)) as away_price
from outcomes
where market = 'h2h'
group by event_id, sport_key, commence_time, home_team, away_team, bookmaker, fetched_at