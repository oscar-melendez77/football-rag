{{ config(severity='warn') }}

-- Articles with neither a summary nor a body are useless for RAG. Tracked, not blocking.
select article_id, publisher, title, url
from {{ ref('articles') }}
where coalesce(summary, '') = '' and body is null
