-- Hecho central del modelo canónico: un renglón de comprobante, con producto
-- resuelto, canal, volumen en unidades base y costo del MES de la venta.
with resolved as (
    select
        s.*,
        coalesce(a.product_id, s.source_product_id) as product_id,
        case when a.product_id is null then false else true end as is_legacy_code
    from {{ ref('stg_sales_lines') }} s
    left join {{ source('landing', 'rule_product_alias') }} a
        on a.source_product_id = s.source_product_id
)

select
    r.line_id,
    r.sale_date,
    r.period,
    r.document_id,
    r.document_type,
    r.customer_id,
    cu.channel,
    cu.named_customers,
    r.source_product_id,
    r.product_id,
    r.is_legacy_code,
    r.quantity,
    r.quantity * coalesce(p.base_units_per_unit, 0) as base_quantity,
    r.unit_price,
    r.discount_pct,
    r.net_amount,
    r.salesperson,
    c.unit_cost,
    r.quantity * c.unit_cost                 as cogs,
    r.net_amount - r.quantity * c.unit_cost  as gross_margin
from resolved r
left join {{ ref('dim_products') }} p
    on p.product_id = r.product_id
left join {{ ref('dim_customers') }} cu
    on cu.customer_id = r.customer_id
left join {{ ref('stg_product_costs') }} c
    on c.product_id = r.product_id
   and c.period = r.period
