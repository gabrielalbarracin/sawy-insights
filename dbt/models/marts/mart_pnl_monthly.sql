-- Estado de resultados mensual de la empresa. No depende del criterio de
-- reparto: a nivel empresa todos los gastos restan igual.
with sales as (
    select
        period,
        sum(net_amount)    as revenue,
        sum(cogs)          as cogs,
        sum(gross_margin)  as gross_margin,
        sum(base_quantity) as base_quantity,
        sum(case when document_type = 'credit_note' then -net_amount else 0 end) as returns_amount
    from {{ ref('fct_sales_lines') }}
    group by period
),

expenses as (
    select
        e.period,
        sum(case when r.behavior = 'variable' then e.amount else 0 end) as variable_expenses,
        sum(case when r.behavior = 'variable' then 0 else e.amount end) as fixed_expenses
    from {{ ref('stg_expenses') }} e
    left join {{ source('landing', 'rule_expense') }} r
        on r.concept = e.concept
    group by e.period
),

periods as (
    select period from sales
    union
    select period from expenses
)

select
    p.period,
    coalesce(s.revenue, 0)            as revenue,
    coalesce(s.returns_amount, 0)     as returns_amount,
    coalesce(s.cogs, 0)               as cogs,
    coalesce(s.gross_margin, 0)       as gross_margin,
    coalesce(s.base_quantity, 0)      as base_quantity,
    coalesce(e.variable_expenses, 0)  as variable_expenses,
    coalesce(e.fixed_expenses, 0)     as fixed_expenses,
    coalesce(s.gross_margin, 0)
      - coalesce(e.variable_expenses, 0)
      - coalesce(e.fixed_expenses, 0) as net_result
from periods p
left join sales s on s.period = p.period
left join expenses e on e.period = p.period
order by p.period
