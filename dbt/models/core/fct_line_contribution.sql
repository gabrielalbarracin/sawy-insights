-- Cada renglón de venta, para cada criterio de reparto, con lo que realmente
-- deja: margen bruto menos los gastos variables que le corresponden.
with allocated as (
    select allocation_method, line_id, sum(allocated_amount) as variable_expenses
    from {{ ref('fct_expense_allocation') }}
    group by allocation_method, line_id
)

select
    m.method as allocation_method,
    s.*,
    coalesce(a.variable_expenses, 0)                  as variable_expenses,
    s.gross_margin - coalesce(a.variable_expenses, 0) as contribution
from {{ ref('fct_sales_lines') }} s
cross join {{ source('landing', 'cfg_allocation_methods') }} m
left join allocated a
    on a.line_id = s.line_id
   and a.allocation_method = m.method
