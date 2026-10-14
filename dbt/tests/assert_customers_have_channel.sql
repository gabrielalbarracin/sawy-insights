-- Todo segmento del ERP tiene que estar mapeado a un canal en client.yaml.
select customer_id, segment
from {{ ref('dim_customers') }}
where channel = 'Sin canal'
