# Supuestos

La consigna pide: *"si falta información, asumila y dejala escrita"*. Cada supuesto tiene su
justificación, su impacto y dónde se cambia. Los que dicen "config" se cambian en
`clients/tostadero_ruta9/client.yaml`, sin tocar código.

## Datos

| # | Supuesto | Por qué | Impacto si está mal | Dónde se cambia |
|---|---|---|---|---|
| D1 | `BLEND1K` es el mismo producto que `CAF-BLEND-1K` (código anterior a la migración). | Sofía avisa que quedaron códigos viejos. `BLEND1K` está inactivo, se llama "BLEND CASA 1KG" y tiene precios idénticos al vigente en cada mes. | Sin unificar, 28 renglones (~1.200 kg, todos de Granos del Sur) quedan sin costo y el Blend Casa parece vender menos. | config `product_aliases` |
| D2 | La caja x6 equivale a 6 kg. Su costo y su precio son por caja. | La descripción dice "CAJA X 6 (1kg c/u)" y el costo de la caja es exactamente 6 veces el del kg. | El volumen y el reparto del flete por kg saldrían mal. | config `base_units_per_unit` |
| D3 | Las notas de crédito (NC) son devoluciones y **ya vienen en negativo** (cantidad e importe). | Así vienen en el export; el mail dice que son café vencido que se cambia. | Restarlas otra vez las duplicaría. La ingesta valida el signo y corta si no coincide. | config `credit_note_sign` |
| D4 | El costo de cada venta es el **costo del mes** de la venta. | Los costos suben ~2,2% por mes. | Usar el costo actual subestimaría el margen de los primeros meses. | modelo `fct_sales_lines` |
| D5 | Se usa el **precio de cada factura**; la lista de precios no se usa para calcular. | Sofía dice que la lista es la de hoy y que no tiene las anteriores. | Ninguno: el importe facturado es el dato real. | — |
| D6 | No se analiza por vendedor. | El campo está vacío en el 88% de los renglones. | — | — |
| D7 | "Consumidor final" y "Venta online" son clientes **agregados**, no personas. | Son códigos genéricos del ERP. | Analizarlos como clientes daría falsos "clientes que se enfrían". | config `channels.named_customers` |

## Negocio

| # | Supuesto | Por qué | Impacto si está mal | Dónde se cambia |
|---|---|---|---|---|
| N1 | Canales: Distribuidor = Granos del Sur; Mayorista = **Cafeterías**; Local = **Mostrador**; Ecommerce = **Online**. | Coincide con los cuatro canales del enunciado. | — | config `channels` |
| N2 | **Flete** y **packaging mayorista** son gastos variables de Distribuidor + Cafeterías. | Las notas de gastos dicen "reparto a cafeterías y distribuidor" y "bolsa valvulada 1kg + caja". | Si el mostrador u online usaran parte del flete, esos canales quedarían algo mejor de lo real. | config `expenses` |
| N3 | El flete se reparte **por kg** como criterio principal, y también **por $ facturado** y **por entrega**. | No hay dato de costo por viaje. Por kg es lo más defendible para café, pero es un supuesto, por eso se muestran los tres. | **Alto**: define si las cafeterías ganan o pierden. Granos del Sur pierde con los tres. | config `driver`, `sensitive`, `default_allocation_method` |
| N4 | Una "entrega" es una factura. | Es la mejor aproximación disponible al número de viajes. | Si varias facturas viajan juntas, el criterio "por entrega" sobrecarga a quien compra seguido. | modelo `fct_expense_allocation` |
| N5 | La comisión del 7% de la plataforma es variable del canal Online. | Las notas lo dicen ("7% sobre venta online"); se verificó que es exactamente el 7% de la venta online de cada mes. | — | config `expenses` |
| N6 | Alquiler, sueldos y energía son **fijos**: no se reparten entre canales, se restan al total. | Repartir fijos entre productos es arbitrario y lleva a malas decisiones (ej. "este producto pierde", cuando sacarlo no ahorra el alquiler). | La rentabilidad por canal es "contribución" (antes de fijos), y así se aclara en el dashboard. | config `expenses.behavior` |
| N7 | Las devoluciones no reciben flete: el café de reemplazo viaja en el próximo reparto ya facturado. | Evita contar el flete dos veces. | Bajo. | modelo `fct_expense_allocation` |
| N8 | "Esta semana" = la semana posterior al último dato (28/06/2025). | Los datos terminan en junio de 2025. | — | — |

## Umbrales de los detectores (defaults en código, ajustables por cliente)

| Umbral | Valor | Significado |
|---|---|---|
| `min_revenue_share_customer` | 2% | Solo se alerta por rentabilidad a clientes con peso real en la facturación. |
| `return_rate_alert` | 8% | Devoluciones por encima de este % de lo vendido son una alerta (el doble → prioridad alta). |
| `cooling_recent_months` / `cooling_ratio` | 2 meses / 50% | "Se enfría" = en los últimos 2 meses compra menos de la mitad de veces que antes. |
| `cross_sell_min_penetration` | 25% | Solo se sugiere un producto que ya compra al menos 1 de cada 4 clientes del canal. |
