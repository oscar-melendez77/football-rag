-- SCD Type 2: one row per player per period with an unchanged status/news/chance.
-- Built deterministically from snapshots, so it can be fully rebuilt at any time.

with snapshots as (
    select
        player_id,
        snapshot_at,
        status,
        news,
        chance_next_round,
        to_json_string(struct(status, news, chance_next_round)) as state_key
    from {{ ref('player_snapshots') }}
),

flagged as (
    select
        *,
        if(
            lag(state_key) over (partition by player_id order by snapshot_at) is distinct from state_key,
            1, 0
        ) as starts_new_period
    from snapshots
),

numbered as (
    select
        *,
        sum(starts_new_period) over (
            partition by player_id
            order by snapshot_at
            rows between unbounded preceding and current row
        ) as period_number
    from flagged
),

periods as (
    select
        player_id,
        period_number,
        any_value(status) as status,
        any_value(news) as news,
        any_value(chance_next_round) as chance_next_round,
        min(snapshot_at) as valid_from,
        max(snapshot_at) as last_seen_at,
        count(*) as snapshots_in_period
    from numbered
    group by player_id, period_number
),

periods_with_end as (
    select
        *,
        lead(valid_from) over (partition by player_id order by valid_from) as valid_to
    from periods
),

latest_player as (
    select player_id, web_name, full_name, team_name, team_short_name, position
    from (
        select
            *,
            row_number() over (partition by player_id order by snapshot_at desc) as rn
        from {{ ref('player_snapshots') }}
    )
    where rn = 1
)

select
    to_hex(md5(concat(cast(p.player_id as string), '|', cast(p.valid_from as string)))) as period_id,
    p.player_id,
    lp.web_name,
    lp.full_name,
    lp.team_name,
    lp.team_short_name,
    lp.position,
    p.status,
    p.news,
    p.chance_next_round,
    p.valid_from,
    p.valid_to,
    p.valid_to is null as is_current,
    p.last_seen_at,
    p.snapshots_in_period
from periods_with_end as p
left join latest_player as lp on lp.player_id = p.player_id