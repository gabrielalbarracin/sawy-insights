-- Clientes con su canal de negocio. named_customers = false indica un cliente
-- "agregado" (mostrador, online): no se analiza como cliente individual.
select
    c.customer_id,
    c.customer_name,
    c.segment,
    coalesce(r.channel, 'Sin canal') as channel,
    coalesce(r.named_customers, true) as named_customers,
    c.discount_pct,
    c.city
from {{ ref('stg_customers') }} c
left join {{ source('landing', 'rule_channel') }} r
    on r.segment = c.segment
