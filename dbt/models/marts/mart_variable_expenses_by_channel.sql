-- Desglose de gastos variables (flete, packaging, comisión...) por canal.
select
    a.allocation_method,
    s.channel,
    a.concept,
    sum(a.allocated_amount) as amount
from {{ ref('fct_expense_allocation') }} a
join {{ ref('fct_sales_lines') }} s on s.line_id = a.line_id
group by a.allocation_method, s.channel, a.concept
