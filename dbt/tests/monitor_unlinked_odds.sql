{{ config(severity='warn') }}

-- Odds events that could not be linked to a match. Usually fixtures beyond the matches lookahead window.
select event_id, competition_code, commence_time, home_team_odds_name, away_team_odds_name
from {{ ref('odds') }}
where not is_linked