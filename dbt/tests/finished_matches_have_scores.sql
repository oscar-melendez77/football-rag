-- A finished match must have a final score. Any row returned here is a data problem.
select match_id, competition_code, status, home_goals, away_goals
from {{ ref('matches') }}
where status = 'FINISHED'
  and (home_goals is null or away_goals is null)