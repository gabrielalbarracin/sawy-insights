select customer_id, customer_name, segment, discount_pct, tax_id, city
from {{ source('landing', 'customers') }}
