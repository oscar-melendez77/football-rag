-- Every row of a league table must satisfy the scoring rules.
select standings_key, played, won, drawn, lost, points
from {{ ref('standings') }}
where played != won + drawn + lost
   or points != 3 * won + drawn