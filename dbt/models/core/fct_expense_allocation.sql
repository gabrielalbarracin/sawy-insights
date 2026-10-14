/*
  Reparte cada gasto VARIABLE del mes entre los renglones de factura de los
  canales a los que aplica, proporcional a un driver:
    - base_units : volumen físico (kg)
    - net_amount : $ facturado
    - deliveries : 1 por comprobante (entrega), repartido entre sus renglones
  Los gastos marcados como sensibles se calculan con TODOS los criterios de
  cfg_allocation_methods; el resto siempre con su driver configurado.
  Las notas de crédito no reciben gasto (supuesto: el reemplazo viaja en el
  próximo reparto ya facturado).
*/
with lines as (
    select line_id, document_id, period, channel, base_quantity, net_amount
    from {{ ref('fct_sales_lines') }}
    where document_type = 'invoice'
),

rules as (
    select concept, driver, is_sensitive
    from {{ source('landing', 'rule_expense') }}
    where behavior = 'variable'
),

expenses as (
    select e.period, e.concept, e.amount, r.driver, r.is_sensitive
    from {{ ref('stg_expenses') }} e
    join rules r on r.concept = e.concept
),

candidates as (
    select
        m.method                                                     as allocation_method,
        e.concept,
        e.period,
        e.amount,
        case when e.is_sensitive then m.method else e.driver end     as driver_used,
        l.line_id,
        l.document_id,
        l.base_quantity,
        l.net_amount
    from expenses e
    cross join {{ source('landing', 'cfg_allocation_methods') }} m
    join {{ source('landing', 'rule_expense_scope') }} sc
        on sc.concept = e.concept
    join lines l
        on l.channel = sc.channel
       and l.period = e.period
),

drivers as (
    select
        *,
        case driver_used
            when 'base_units' then base_quantity
            when 'net_amount' then net_amount
            when 'deliveries' then 1.0 / count(*) over (
                partition by allocation_method, concept, period, document_id)
        end as driver_value
    from candidates
)

select
    allocation_method,
    concept,
    period,
    line_id,
    driver_used,
    amount * driver_value / nullif(sum(driver_value) over (
        partition by allocation_method, concept, period), 0) as allocated_amount
from drivers
