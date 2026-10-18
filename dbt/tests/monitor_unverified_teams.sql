{{ config(severity='warn') }}

-- Teams without a confirmed Wikipedia article. Fix by adding a row to the override seed after review.
select team_id, team_name, wiki_title, wiki_match_status
from {{ ref('teams') }}
where wiki_match_status in ('unverified', 'not_in_snapshot')