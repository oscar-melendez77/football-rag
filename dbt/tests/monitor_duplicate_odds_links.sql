{{ config(severity='warn') }}

-- Two odds events linked to the same match means one link is wrong.
select match_id, count(*) as events
from {{ ref('odds') }}
where match_id is not null
group by match_id
having count(*) > 1