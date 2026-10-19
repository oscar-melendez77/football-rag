-- After removing the margin, the three probabilities must add up to 1.
select event_id, prob_home + prob_draw + prob_away as total
from {{ ref('odds') }}
where abs(prob_home + prob_draw + prob_away - 1) > 0.001