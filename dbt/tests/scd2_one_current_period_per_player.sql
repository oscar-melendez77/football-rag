-- SCD2 rule: every player has exactly one current period.
select player_id, countif(is_current) as current_periods
from {{ ref('player_availability') }}
group by player_id
having countif(is_current) != 1