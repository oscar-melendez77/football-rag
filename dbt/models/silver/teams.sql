-- One row per club. The team list comes from matches (a team exists if it plays);
-- background comes from the latest weekly Wikipedia snapshot; a reviewed seed fixes edge cases.

with match_teams as (
    select home_team_id as team_id, home_team_name as team_name, competition_code
    from {{ ref('matches') }}
    union all
    select away_team_id, away_team_name, competition_code
    from {{ ref('matches') }}
),

team_base as (
    select
        team_id,
        any_value(team_name) as team_name,
        array_agg(distinct competition_code order by competition_code) as competitions
    from match_teams
    group by team_id
),

wiki_files as (
    select
        payload,
        row_number() over (order by run_date desc, loaded_at desc) as file_rank
    from {{ source('bronze', 'raw_files') }}
    where source = 'wikipedia'
),

wiki as (
    select
        cast(json_value(t, '$.team_id') as int64) as team_id,
        json_value(t, '$.short_name') as short_name,
        json_value(t, '$.tla') as tla,
        json_value(t, '$.wiki_title') as wiki_title,
        json_value(t, '$.wiki_url') as wiki_url,
        json_value(t, '$.wikidata_id') as wikidata_id,
        json_value(t, '$.resolution_method') as resolution_method,
        cast(json_value(t, '$.is_football_club') as bool) as is_football_club,
        json_value(t, '$.extract') as wiki_extract,
        cast(json_value(t, '$.extract_chars') as int64) as wiki_extract_chars,
        json_value(t, '$.wikidata_claims.inception[0].mainsnak.datavalue.value.time') as inception_raw,
        json_value(t, '$.wikidata_claims.home_venue[0].mainsnak.datavalue.value.id') as home_venue_qid,
        json_value(t, '$.wikidata_claims.country[0].mainsnak.datavalue.value.id') as country_qid
    from wiki_files,
        unnest(json_query_array(payload, '$.teams')) as t
    where file_rank = 1
),

overrides as (
    select team_name, wiki_title, reason
    from {{ ref('team_wikipedia_overrides') }}
)

select
    b.team_id,
    b.team_name,
    w.short_name,
    w.tla,
    b.competitions,
    coalesce(o.wiki_title, w.wiki_title) as wiki_title,
    w.wiki_url,
    w.wikidata_id,
    safe_cast(substr(w.inception_raw, 2, 4) as int64) as founded_year,
    w.home_venue_qid,
    w.country_qid,
    w.wiki_extract,
    w.wiki_extract_chars,
    case
        when o.team_name is not null then 'manual_override'
        when w.is_football_club then 'verified'
        when w.team_id is null then 'not_in_snapshot'
        else 'unverified'
    end as wiki_match_status,
    w.resolution_method,
    o.reason as override_reason
from team_base as b
left join wiki as w on w.team_id = b.team_id
left join overrides as o on o.team_name = b.team_name