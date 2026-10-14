-- Conciliación: el modelo no puede "perder" ni "inventar" facturación
-- respecto de lo que mandó el ERP.
select m.total as modeled, l.total as landed
from (select sum(net_amount) as total from {{ ref('fct_sales_lines') }}) m
cross join (select sum(net_amount) as total from {{ source('landing', 'sales_lines') }}) l
where abs(m.total - l.total) > 0.01
