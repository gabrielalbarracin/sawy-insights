select
    line_id,
    sale_date,
    period,
    document_id,
    document_type,
    customer_id,
    product_id as source_product_id,   -- puede ser un código viejo; se resuelve en core
    quantity,
    unit_price,
    discount_pct,
    net_amount,
    salesperson
from {{ source('landing', 'sales_lines') }}
