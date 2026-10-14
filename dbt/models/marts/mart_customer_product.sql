-- Qué compra cada cliente (base para detectar oportunidades de venta cruzada).
select
    customer_id,
    channel,
    product_id,
    sum(net_amount) as revenue,
    sum(quantity)   as quantity
from {{ ref('fct_sales_lines') }}
where named_customers
  and document_type = 'invoice'
group by customer_id, channel, product_id
