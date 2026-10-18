{{ config(severity='warn') }}

-- Reports rows where the source sent a datetime instead of a status and silver repaired it.
-- severity='warn' shows them without failing the pipeline: an upstream issue we track, not a blocker.
select match_id, competition_code, status_raw, status
from {{ ref('matches') }}
where status_was_repaired