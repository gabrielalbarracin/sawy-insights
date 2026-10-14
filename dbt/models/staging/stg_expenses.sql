select period, concept, amount, notes
from {{ source('landing', 'expenses') }}
