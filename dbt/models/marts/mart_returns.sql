-- Devoluciones (notas de crédito) vs. lo vendido, por canal y producto.
select
    channel,
    product_id,
    sum(case when document_type = 'invoice' then quantity else 0 end)          as sold_quantity,
    -sum(case when document_type = 'credit_note' then quantity else 0 end)     as returned_quantity,
    -sum(case when document_type = 'credit_note' then net_amount else 0 end)   as returned_amount,
    -sum(case when document_type = 'credit_note' then cogs else 0 end)         as returned_cost,
    count(distinct case when document_type = 'credit_note' then document_id end) as credit_notes,
    case when sum(case when document_type = 'invoice' then quantity else 0 end) = 0 then null
         else -sum(case when document_type = 'credit_note' then quantity else 0 end) * 1.0
              / sum(case when document_type = 'invoice' then quantity else 0 end)
    end as return_rate
from {{ ref('fct_sales_lines') }}
group by channel, product_id
