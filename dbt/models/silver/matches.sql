-- One clean row per match, from daily runs and the season backfill.
-- The same match appears in many files, so we keep only its latest version.
-- Known upstream issue (Oct 2026): football-data.org sometimes puts the kickoff
-- datetime in the status field for upcoming CL matches. We repair it here and flag it.

with files as (
    select object_path, payload
    from {{ source('bronze', 'raw_files') }}
    where source in ('matches', 'matches_backfill')
),

exploded as (
    select
        timestamp(json_value(f.payload, '$.fetched_at')) as fetched_at,
        json_value(f.payload, '$.competition') as competition_code,
        f.object_path,
        m as match_json
    from files as f,
        unnest(json_query_array(f.payload, '$.matches')) as m
),

typed as (
    select
        cast(json_value(match_json, '$.id') as int64) as match_id,
        competition_code,
        json_value(match_json, '$.competition.name') as competition_name,
        cast(json_value(match_json, '$.season.id') as int64) as season_id,
        date(json_value(match_json, '$.season.startDate')) as season_start_date,
        timestamp(json_value(match_json, '$.utcDate')) as kickoff_utc,
        json_value(match_json, '$.status') as status_raw,
        case
            when safe.timestamp(json_value(match_json, '$.status')) is not null then 'TIMED'
            else json_value(match_json, '$.status')
        end as status,
        safe.timestamp(json_value(match_json, '$.status')) is not null as status_was_repaired,
        cast(json_value(match_json, '$.matchday') as int64) as matchday,
        json_value(match_json, '$.stage') as stage,
        cast(json_value(match_json, '$.homeTeam.id') as int64) as home_team_id,
        json_value(match_json, '$.homeTeam.name') as home_team_name,
        cast(json_value(match_json, '$.awayTeam.id') as int64) as away_team_id,
        json_value(match_json, '$.awayTeam.name') as away_team_name,
        cast(json_value(match_json, '$.score.fullTime.home') as int64) as home_goals,
        cast(json_value(match_json, '$.score.fullTime.away') as int64) as away_goals,
        cast(json_value(match_json, '$.score.halfTime.home') as int64) as home_goals_ht,
        cast(json_value(match_json, '$.score.halfTime.away') as int64) as away_goals_ht,
        json_value(match_json, '$.score.winner') as winner,
        json_value(match_json, '$.score.duration') as duration,
        timestamp(json_value(match_json, '$.lastUpdated')) as source_last_updated,
        fetched_at,
        object_path
    from exploded
),

ranked as (
    select
        *,
        row_number() over (
            partition by match_id
            order by source_last_updated desc, fetched_at desc
        ) as version_rank
    from typed
)

select * except (version_rank)
from ranked
where version_rank = 1