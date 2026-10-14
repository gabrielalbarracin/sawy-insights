-- Actividad de compra por cliente y mes (solo clientes con nombre propio).
select
    customer_id,
    period,
    count(distinct case when document_type = 'invoice' then document_id end) as invoices,
    sum(net_amount)                                                           as revenue,
    max(case when document_type = 'invoice' then sale_date end)               as last_invoice_date
from {{ ref('fct_sales_lines') }}
where named_customers
group by customer_id, period
