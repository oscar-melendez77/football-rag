-- One row per odds event: market-implied probabilities averaged across bookmakers
-- (margin removed), linked to football-data matches by league, kickoff time and team-name similarity.

with latest_quotes as (
    select * except (fetch_rank)
    from (
        select
            *,
            dense_rank() over (partition by event_id order by fetched_at desc) as fetch_rank
        from {{ ref('odds_quotes') }}
    )
    where fetch_rank = 1
      and home_price > 0 and draw_price > 0 and away_price > 0
),

normalized as (
    select
        *,
        (1 / home_price) / (1 / home_price + 1 / draw_price + 1 / away_price) as p_home,
        (1 / draw_price) / (1 / home_price + 1 / draw_price + 1 / away_price) as p_draw,
        (1 / away_price) / (1 / home_price + 1 / draw_price + 1 / away_price) as p_away,
        (1 / home_price + 1 / draw_price + 1 / away_price) - 1 as bookmaker_margin
    from latest_quotes
),

events as (
    select
        event_id,
        any_value(sport_key) as sport_key,
        any_value(commence_time) as commence_time,
        any_value(home_team) as home_team_odds_name,
        any_value(away_team) as away_team_odds_name,
        max(fetched_at) as fetched_at,
        count(*) as bookmaker_count,
        avg(p_home) as prob_home,
        avg(p_draw) as prob_draw,
        avg(p_away) as prob_away,
        avg(bookmaker_margin) as avg_bookmaker_margin
    from normalized
    group by event_id
),

events_with_league as (
    select e.*, s.competition_code
    from events as e
    left join {{ ref('odds_sport_keys') }} as s on s.sport_key = e.sport_key
),

candidates as (
    select
        e.event_id,
        m.match_id,
        edit_distance(
            {{ normalize_team_name('e.home_team_odds_name') }},
            {{ normalize_team_name('m.home_team_name') }}
        ) + edit_distance(
            {{ normalize_team_name('e.away_team_odds_name') }},
            {{ normalize_team_name('m.away_team_name') }}
        ) as match_score
    from events_with_league as e
    join {{ ref('matches') }} as m
        on m.competition_code = e.competition_code
        and abs(timestamp_diff(m.kickoff_utc, e.commence_time, minute)) <= 180
),

best_match as (
    select event_id, match_id, match_score
    from (
        select
            *,
            row_number() over (partition by event_id order by match_score, match_id) as rn
        from candidates
    )
    where rn = 1
      and match_score <= 12
)

select
    e.*,
    b.match_id,
    b.match_score,
    b.match_id is not null as is_linked
from events_with_league as e
left join best_match as b on b.event_id = e.event_id