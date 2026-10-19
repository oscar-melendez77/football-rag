-- Within a competition, every goal scored is a goal conceded by someone: totals must balance.
select competition_code, sum(goals_for) as total_for, sum(goals_against) as total_against
from {{ ref('standings') }}
group by competition_code
having sum(goals_for) != sum(goals_against)