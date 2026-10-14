-- Maestro de productos vigente. Los códigos viejos (alias) no son productos:
-- sus ventas se reasignan al código vigente en fct_sales_lines.
select
    p.product_id,
    p.product_name,
    p.category,
    p.unit_of_measure,
    p.list_price,
    p.is_active,
    coalesce(u.base_units_per_unit, 0) as base_units_per_unit
from {{ ref('stg_products') }} p
left join {{ source('landing', 'rule_product_units') }} u
    on u.product_id = p.product_id
where p.product_id not in (
    select source_product_id from {{ source('landing', 'rule_product_alias') }}
)
