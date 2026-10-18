-- One row per article: the text corpus for RAG.
-- Unifies Guardian API (full text) and RSS (title + summary), strips HTML,
-- and keeps one row per URL (Guardian API version wins, then newest snapshot).

with guardian_files as (
    select
        timestamp(json_value(payload, '$.fetched_at')) as fetched_at,
        a
    from {{ source('bronze', 'raw_files') }},
        unnest(json_query_array(payload, '$.articles')) as a
    where source in ('guardian', 'guardian_backfill')
),

guardian_rows as (
    select
        json_value(a, '$.webUrl') as url,
        'guardian_api' as source_channel,
        'guardian' as publisher,
        'en' as language,
        json_value(a, '$.webTitle') as title,
        {{ clean_html("json_value(a, '$.fields.trailText')") }} as summary,
        nullif(json_value(a, '$.fields.bodyText'), '') as body,
        timestamp(json_value(a, '$.webPublicationDate')) as published_at,
        json_value(a, '$.fields.byline') as author,
        array(select json_value(t, '$.webTitle') from unnest(json_query_array(a, '$.tags')) as t) as tags,
        fetched_at,
        1 as source_priority
    from guardian_files
),

rss_files as (
    select
        timestamp(json_value(payload, '$.fetched_at')) as fetched_at,
        json_value(payload, '$.feed_name') as feed_name,
        json_value(payload, '$.language') as language,
        e
    from {{ source('bronze', 'raw_files') }},
        unnest(json_query_array(payload, '$.entries')) as e
    where source = 'rss'
),

rss_rows as (
    select
        json_value(e, '$.link') as url,
        concat('rss:', feed_name) as source_channel,
        split(feed_name, '_')[offset(0)] as publisher,
        language,
        {{ clean_html("json_value(e, '$.title')") }} as title,
        {{ clean_html("json_value(e, '$.summary')") }} as summary,
        cast(null as string) as body,
        safe.timestamp(json_value(e, '$.published')) as published_at,
        json_value(e, '$.author') as author,
        json_value_array(e, '$.tags') as tags,
        fetched_at,
        2 as source_priority
    from rss_files
),

unioned as (
    select * from guardian_rows
    union all
    select * from rss_rows
),

normalized as (
    select
        *,
        rtrim(regexp_replace(lower(url), r'[?#].*$', ''), '/') as url_normalized
    from unioned
    where url is not null
),

ranked as (
    select
        *,
        row_number() over (
            partition by url_normalized
            order by source_priority, (body is not null) desc, fetched_at desc
        ) as version_rank
    from normalized
)

select
    to_hex(md5(url_normalized)) as article_id,
    url,
    url_normalized,
    source_channel,
    publisher,
    language,
    title,
    summary,
    body,
    body is not null as has_full_text,
    coalesce(array_length(split(body, ' ')), 0) as body_word_count,
    published_at,
    author,
    tags,
    fetched_at
from ranked
where version_rank = 1
