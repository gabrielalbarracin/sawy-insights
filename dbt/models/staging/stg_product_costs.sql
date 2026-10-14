select product_id, period, unit_cost, currency
from {{ source('landing', 'product_costs') }}
