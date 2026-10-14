{# Usa el nombre de schema tal cual (staging, core, marts) en lugar de
   concatenarlo con el schema del target, que es el default de dbt. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}{{ target.schema }}{%- else -%}{{ custom_schema_name | trim }}{%- endif -%}
{%- endmacro %}
