-- SCD2 rule: a closed period must end after it starts.
select period_id, player_id, valid_from, valid_to
from {{ ref('player_availability') }}
where valid_to is not null
  and valid_to <= valid_from