-- Cada gasto variable del mes tiene que repartirse COMPLETO, con cada criterio.
-- Si falla: hay un gasto variable en un mes sin ventas en sus canales.
with expected as (
    select m.method as allocation_method, e.concept, e.period, e.amount
    from {{ ref('stg_expenses') }} e
    join {{ source('landing', 'rule_expense') }} r
        on r.concept = e.concept and r.behavior = 'variable'
    cross join {{ source('landing', 'cfg_allocation_methods') }} m
),
allocated as (
    select allocation_method, concept, period, sum(allocated_amount) as amount
    from {{ ref('fct_expense_allocation') }}
    group by allocation_method, concept, period
)
select e.*, a.amount as allocated
from expected e
left join allocated a
    on a.allocation_method = e.allocation_method
   and a.concept = e.concept
   and a.period = e.period
where a.amount is null or abs(a.amount - e.amount) > 1
