select product_id, product_name, unit_of_measure, category, list_price, is_active
from {{ source('landing', 'products') }}
