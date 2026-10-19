-- One row per team: background (Wikipedia) plus current situation (form, position, absences).

select
    t.team_id,
    t.team_name,
    t.short_name,
    t.tla,
    t.competitions,
    t.founded_year,
    t.wiki_title,
    t.wiki_url,
    t.wiki_match_status,
    f.form_last5,
    f.points_last5,
    f.domestic_competition,
    f.domestic_position,
    f.domestic_points,
    a.players_out,
    a.players_doubtful,
    left(t.wiki_extract, 1500) as wiki_summary
from {{ ref('teams') }} as t
left join {{ ref('team_form') }} as f on f.team_id = t.team_id
left join {{ ref('team_availability') }} as a on a.team_id = t.team_id