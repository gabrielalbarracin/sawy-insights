# Arquitectura

## Flujo

```
python -m sawy build --client <id>
│
├─ 1. Ingesta (sawy/ingest)                                    POR CLIENTE → GENÉRICO
│     client.yaml ──▶ leer archivo ─▶ renombrar ─▶ tipar ─▶ normalizar signos ─▶ CONTRATO
│                                                                              │
│     landing.sales_lines, products, customers, product_costs, expenses  ◀──────┘
│     landing.rule_* / cfg_*  (reglas de negocio del YAML, como tablas)
│
├─ 2. dbt build (dbt/) ─ modelos + tests en orden de dependencias
│     staging  ─ vistas 1:1 sobre landing
│     core     ─ dim_products, dim_customers, fct_sales_lines  (MODELO CANÓNICO)
│                fct_expense_allocation (gasto variable × renglón × criterio)
│                fct_line_contribution  (renglón × criterio, con contribución)
│     marts    ─ mart_pnl_monthly, mart_contribution_by_{channel,product,customer,...},
│                mart_customer_monthly, mart_customer_product, mart_returns
│
├─ 3. Hallazgos (sawy/insights) ─ solo leen marts (+ dims)
│     KPIs + detectores (con capacidades requeridas) ─▶ InsightsReport (JSON)
│
├─ 4. IA (sawy/ai)
│     caché válida? ─sí─▶ usar
│        └─no─▶ hay clave? ─no─▶ plantilla determinística
│                  └─sí─▶ LLM: Gemini / OpenAI (JSON Schema estricto, o modo JSON) ─▶ guardrails ─✗─▶ reintento con errores ─✗─▶ plantilla
│                                                        └─✓─▶ guardar caché
│
└─ 5. Dashboard (sawy/report) ─ HTML estático + output/<id>/insights.json
```

## Por qué estas capas

| Capa | Responsabilidad | Qué NO hace |
|---|---|---|
| Ingesta | Estructura: columnas, formatos, tipos, signos. Valida contratos. | No interpreta el negocio (alias, canales, reparto). |
| dbt core | Semántica: aplica las reglas del cliente y construye el modelo canónico. | No conoce a ningún cliente: lee reglas como datos. |
| dbt marts | La "API" del análisis: agregados estables y testeados. | No tiene lógica de presentación. |
| Detectores | Convertir números en hallazgos priorizados, con los hechos calculados. | No redactan para el usuario final. |
| IA | Redactar, agrupar y priorizar en lenguaje simple. | **No calcula ni escribe cifras.** |
| Reporte | Presentar. | No calcula nada que no venga de marts o hallazgos. |

## Modelo canónico

```
dim_customers (customer_id, channel, named_customers, discount_pct)
      │
fct_sales_lines (line_id, sale_date, period, document_id, document_type,
      │          customer_id, product_id, source_product_id, is_legacy_code,
      │          quantity, base_quantity, net_amount, unit_cost, cogs, gross_margin)
      │
dim_products (product_id, category, base_units_per_unit)

fct_expense_allocation (allocation_method, concept, period, line_id, allocated_amount)
fct_line_contribution  (allocation_method, line_id, ..., variable_expenses, contribution)
```

**Convenciones:** las notas de crédito restan (negativas); `period` es el primer día del mes;
`base_quantity` es el volumen físico (kg en este cliente, puede ser litros, m², unidades);
`contribution` = margen bruto − gastos variables asignados (antes de fijos).

## Reparto de gastos

`fct_expense_allocation` reparte cada gasto variable del mes entre los renglones de factura de
los canales configurados, proporcional a un driver:

| Driver | Valor por renglón |
|---|---|
| `base_units` | volumen físico del renglón |
| `net_amount` | $ facturado del renglón |
| `deliveries` | 1 ÷ cantidad de renglones de su factura (cada factura = 1 entrega) |

Los gastos marcados `sensitive: true` se calculan con todos los criterios de
`analysis.allocation_methods`; los demás, siempre con su driver. Tres tests garantizan la
consistencia: reparto completo, invariancia del total entre criterios y conciliación con el ERP.

## La IA, en detalle

**Entrada:** contexto del negocio, creencias del dueño, un diccionario de hechos
(`kpi.*`, `F<n>.*`) con significado y valor formateado, y los hallazgos ya redactados.

**Salida** (JSON Schema estricto): `headline`, `summary[]`, `actions[]` (con `finding_ids`) y
`beliefs[]` (veredicto + explicación).

**Guardrails** (`sawy/ai/guardrails.py`):
1. Toda cifra va como `[[clave]]`; las claves tienen que existir.
2. Sacando placeholders y nombres permitidos (clientes y productos, que pueden tener dígitos como
   "Blend Casa 1 kg"), **no puede quedar ningún dígito**.
3. Entre 3 y 5 acciones, cada una con al menos un hallazgo existente.
4. Una evaluación por cada creencia.

**Caché:** la clave es el hash de los hechos, los IDs de hallazgos y la versión del prompt.
Si cambian los datos o el prompt, se regenera. La caché se versiona en el repo para que el
dashboard muestre textos de IA sin necesidad de clave.

## Cómo sumar...

**Un cliente:** copiar `clients/tostadero_ruta9`, reemplazar `raw/`, ajustar `client.yaml` y
`python -m sawy build --client <nuevo>`. Los errores de mapeo aparecen en la ingesta (contratos)
o en `dbt build` (relaciones, costos faltantes, canales sin mapear), con el detalle de qué falta.

**Un detector:** una función en `sawy/insights/detectors.py` decorada con
`@detector("capacidad", ...)` que lee marts y devuelve `Finding`s con sus `facts`. La IA y el
dashboard lo toman automáticamente.

**Un mart:** un `.sql` en `dbt/models/marts/`. Para cortes de contribución nuevos alcanza con
`{{ contribution_rollup(['dimension']) }}`.

**Otro proveedor de IA:** una entrada en `PROVIDERS` (`sawy/ai/providers.py`) si expone una API
compatible con OpenAI (Gemini, Groq, Ollama, etc.); si no, una función `complete` propia. El resto
(prompt, schema, guardrails, caché) no cambia.

**Otro motor:** otra implementación de `Warehouse` (`sawy/warehouse.py`) y otro adaptador en
`dbt/profiles.yml`. El SQL de los modelos es estándar: no usa funciones propias de DuckDB.
