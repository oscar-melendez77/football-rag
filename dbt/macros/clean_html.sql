{% macro clean_html(expr) -%}
    trim(regexp_replace(
        replace(replace(replace(replace(replace(replace(
            regexp_replace({{ expr }}, r'<[^>]+>', ' '),
        '&nbsp;', ' '), '&amp;', '&'), '&quot;', '"'), '&#39;', "'"), '&lt;', '<'), '&gt;', '>'),
    r'\s+', ' '))
{%- endmacro %}
