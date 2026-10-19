{% macro normalize_team_name(expr) -%}
    trim(regexp_replace(regexp_replace(regexp_replace(regexp_replace(
        replace(regexp_replace(normalize(lower({{ expr }}), NFD), r'\p{M}', ''), '&', ' and '),
    r'[^a-z0-9 ]', ' '),
    r'\b(fc|cf|afc|sc|ac|as|ss|ssc|fk|sk|cd|ud|rc|club|de|calcio|the)\b', ' '),
    r'\s+', ' '), r'^\s+|\s+$', ''))
{%- endmacro %}