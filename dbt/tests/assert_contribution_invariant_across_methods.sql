-- Cambiar el criterio de reparto mueve plata ENTRE canales/clientes,
-- pero el total de la empresa tiene que ser el mismo.
with totals as (
    select allocation_method, sum(contribution) as total
    from {{ ref('fct_line_contribution') }}
    group by allocation_method
)
select max(total) - min(total) as spread
from totals
having max(total) - min(total) > 1
