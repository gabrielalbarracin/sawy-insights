{#
  Agrega fct_line_contribution por las dimensiones pedidas, para cada criterio
  de reparto. Una sola definición de "contribución" para todos los cortes
  (canal, producto, cliente...): si cambia la fórmula, cambia en un lugar.
#}
{% macro contribution_rollup(dims) -%}
select
    allocation_method,
    {{ dims | join(',\n    ') }},
    sum(net_amount)                                   as revenue,
    sum(cogs)                                         as cogs,
    sum(gross_margin)                                 as gross_margin,
    sum(variable_expenses)                            as variable_expenses,
    sum(contribution)                                 as contribution,
    sum(base_quantity)                                as base_quantity,
    count(distinct case when document_type = 'invoice' then document_id end) as invoices,
    case when sum(net_amount) = 0 then null
         else sum(contribution) * 1.0 / sum(net_amount) end as contribution_margin_pct
from {{ ref('fct_line_contribution') }}
group by allocation_method, {{ dims | join(', ') }}
{%- endmacro %}
