{% macro normalize_text(expr) -%}
    trim(regexp_replace(regexp_replace(regexp_replace(
        normalize(lower({{ expr }}), NFD),
    r'\p{M}', ''), r'[^a-z0-9 ]', ' '), r'\s+', ' '))
{%- endmacro %}