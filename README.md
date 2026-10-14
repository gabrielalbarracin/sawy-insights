# Sawy · Caso práctico: Tostadero Ruta 9

Herramienta de visibilidad de negocio construida sobre los exports del ERP de Sofía.
Responde **si el negocio gana plata y con qué**, y propone **acciones concretas para esta semana**.

> **Ver el dashboard sin instalar nada:** https://gabrielalbarracin.github.io/sawy-insights/
> (o abrir [`docs/index.html`](docs/index.html) descargado del repo)

---

## Lo que dicen los datos (en 30 segundos)

| | |
|---|---|
| **¿Gana plata?** | No. En 6 meses facturó **$120,5 M** y perdió **$1,1 M**; 5 de 6 meses en rojo. |
| **¿Con qué pierde?** | Con **Granos del Sur**: es el 35% de la facturación, pero con 40% de descuento y el flete a cargo del tostadero pierde plata **con los 3 criterios de reparto del flete que probamos** (entre $0,1 M y $0,8 M por mes). Con el criterio por kg, el descuento no debería superar el **~33%**. |
| **¿Con qué gana?** | Con el **online** (el canal "hobby"): 27% de la facturación y el canal que más deja (48% después de gastos variables). |
| **¿Por qué "facturamos cada vez más"?** | Por la inflación: entre el principio y el final del semestre la facturación subió 3,9% en pesos y el volumen bajó 6,9% en kg. |

Además: el Brasil 1 kg vuelve vencido en el 11% de lo vendido a cafeterías, cuatro cafeterías bajaron fuerte la frecuencia de compra y el Etiopía (28% de margen en el canal) todavía no lo compran 16 cafeterías.

---

## Cómo levantarlo

**Opción A: Docker (recomendada, un comando)**

```bash
git clone https://github.com/gabrielalbarracin/sawy-insights.git
cd sawy-insights
docker compose up --build
```

Abrir **http://localhost:8000**. El primer build tarda un par de minutos porque instala dependencias; después tarda segundos.

**Opción B: Python local (3.10+)**

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m sawy build             # ingesta → dbt → hallazgos → IA → dashboard
python -m sawy serve             # http://localhost:8000
```

**IA (opcional).** Sin clave todo funciona: los textos salen de la caché versionada
(`clients/<cliente>/ai_narrative.cache.json`) o, si los datos cambiaron, de una plantilla sin IA.
Para regenerarlos con IA:

```bash
cp .env.example .env               # y completar GEMINI_API_KEY (u OPENAI_API_KEY)
docker compose run --rm sawy python -m sawy build --refresh-ai --publish
```

**Tests:** `docker compose run --rm sawy pytest -q` (o `pytest -q` en local).

---

## Cómo está pensado

El caso tiene cuatro etapas: **conectar → modelar → IA → mostrar**. La conexión y la
presentación dependen de cada cliente; el foco está en que **el modelado y la IA sirvan
para cualquier cliente**, cambiando solo configuración.

```
            POR CLIENTE (configuración)                      GENÉRICO (igual para todos)
 ┌────────────────────────────────────────┐   ┌──────────────────────────────────────────────────────────┐
 ERP / CSV ─▶ client.yaml: mapeo + reglas ─▶ landing ─▶ dbt: staging → core → marts ─▶ detectores ─▶ IA ─▶ dashboard
              (columnas, formatos, alias,    (modelo      (tests de datos e           (hallazgos     (redacta,   (HTML
               unidades, canales, gastos)     canónico)    invariantes de negocio)     con números)   no calcula) estático)
```

### Decisiones y por qué

**1. Lo estructural y lo semántico van separados.**
La ingesta (`sawy/ingest`) solo resuelve **cómo leer** el archivo: nombres de columnas, formatos,
tipos y signo de las notas de crédito. **Qué significa** cada dato (que `BLEND1K` es un código viejo
del Blend 1 kg, que la caja x6 son 6 kg, que "Mayorista" son cafeterías, cómo se reparte el flete)
son reglas de negocio. Viajan como tablas desde `client.yaml` y se aplican en dbt, a la vista y testeadas.
Un cliente nuevo es un YAML nuevo, no código nuevo.

**2. Modelo canónico con contratos.**
Todo ERP termina en las mismas 5 tablas (`sales_lines`, `products`, `customers`, `product_costs`,
`expenses`). Los contratos (`sawy/ingest/contracts.py`) frenan un archivo mal mapeado en la entrada,
con un mensaje accionable ("el mapeo pide `total_linea` y no está en ventas.csv"), en lugar de dejar
pasar un número raro hasta el dashboard. La validación es vectorizada, así que escala.

**3. Los tests de dbt verifican reglas de negocio, no solo la forma de los datos.**
Además de `unique`, `not_null` y `relationships`:
- **Conciliación:** el total modelado tiene que ser igual al total del ERP.
- **Reparto completo:** cada peso de gasto variable se asigna, con cada criterio.
- **Invariancia:** cambiar el criterio de reparto mueve plata entre canales, pero no cambia el total.
- **Costo obligatorio:** sin costo del mes no hay margen; si falta, el build falla.

**4. El supuesto más discutible se muestra, no se esconde.**
El ERP no asigna el flete a clientes, así que hay que repartirlo, y **la conclusión depende de cómo**.
Por kg, las cafeterías ganan $1,1 M; por entrega, pierden $3,1 M. El modelo calcula los tres
criterios (`base_units`, `net_amount`, `deliveries`), el dashboard los deja alternar, y un detector
avisa cuando un resultado cambia de signo según el criterio. Granos del Sur pierde con los tres, y
por eso esa recomendación es firme y la de cafeterías es "medir antes de decidir".

**5. Detectores genéricos que declaran qué necesitan.**
Cada detector (`sawy/insights/detectors.py`) lee solo los marts y declara sus requisitos
(`base_units`, `named_customers`, `credit_notes`...). Si un cliente no tiene, por ejemplo, unidades
físicas, el detector no corre y queda registrado. Sumar un detector es escribir una función.

**6. La IA redacta y prioriza, pero no escribe números.**
El riesgo de un LLM en un producto de datos es que invente o transcriba mal una cifra. Acá eso es
imposible por construcción:
- El modelo recibe hechos ya calculados y **solo puede citarlos con placeholders** (`[[F1.monthly_loss]]`).
  Los reemplaza código determinístico.
- **Validación posterior:** si hay dígitos escritos a mano, placeholders inexistentes o acciones sin
  respaldo, la salida se rechaza. Se reintenta una vez con los errores y, si vuelve a fallar, se usa
  la plantilla determinística.
- **Salida estructurada** (JSON Schema estricto), **caché por hash** de los hechos más la versión del
  prompt (no se paga dos veces lo mismo), y cada acción **enlaza al hallazgo** que la respalda.
- La IA también contrasta **lo que Sofía cree** (del mail de onboarding) con los datos, con tacto.

**7. Dashboard estático, sin dependencias de JavaScript.**
Los gráficos se generan en Python como HTML/SVG: funciona offline, se publica en GitHub Pages y no se
rompe porque falte un CDN. Tiene modo oscuro, tooltips con mouse, teclado y toque, tablas accesibles
y se lee bien en el celular. Está escrito para Sofía: "¿Estás ganando plata?", no "EBITDA".

---

## Stack y cómo escalaría

| | Elección | Por qué |
|---|---|---|
| Lenguaje | Python | El ecosistema de datos e IA. Pydantic para contratos y configuración. |
| Motor | **DuckDB** | SQL analítico embebido, sin infraestructura, rápido con millones de filas. Un archivo por cliente. |
| Modelado | **dbt** | SQL versionado, linaje, tests de datos y documentación. Es el estándar de la industria y cambiar de motor es cambiar de adaptador. |
| IA | Gemini u OpenAI, salida estructurada | Un solo cliente (SDK de OpenAI) contra APIs compatibles: cambiar de proveedor es una variable de entorno (`sawy/ai/providers.py`). Si un proveedor no soporta JSON Schema estricto, cae a modo JSON; la validación posterior es la misma. |
| Entrega | HTML estático (Jinja) | Sin servidor, versionable y se comparte con un link. |
| Empaquetado | Docker Compose | `docker compose up` y listo, en cualquier máquina. |

**¿Escala?** Lo que crece en Sawy es la **cantidad de clientes**, no el volumen de cada uno (una pyme
tiene MB o pocos GB). Cada cliente es un pipeline independiente y paralelizable. El **diseño** escala
tal cual; la **infraestructura** de este repo es, a propósito, de una sola máquina. Para producción
cambiarían solo las piezas de infraestructura:

| Pieza | Este repo | Producción, decenas de clientes | Producción, cientos / benchmarks entre clientes |
|---|---|---|---|
| Extracción   | CSV | Conectores por ERP (dlt / Airbyte) → Parquet en S3/GCS                                          | igual |
| Motor        | DuckDB local | DuckDB por cliente o MotherDuck | BigQuery / Snowflake (**mismo dbt**, otro adaptador) |
| Orquestación | un comando | Dagster / Prefect, corrida diaria por cliente                                    | igual + SLAs y alertas |
| IA           | script + caché | worker con cola, observabilidad (Langfuse) y evals                                   | igual |
| Entrega      | HTML estático | web app + API sobre los marts + email/WhatsApp                                        | igual |
| Secretos     | `.env` | gestor de secretos                                                                           | igual |

El modelo canónico, los modelos dbt, los detectores, la capa de IA y la configuración por cliente
**no se reescriben** para escalar.

---

## Consigna 2: si entra otro cliente, de otro rubro y con otro ERP

| Sirve tal cual | Se configura (sin código) | Se rehace o se agrega |
|---|---|---|
| Modelo canónico y contratos | Mapeo de columnas y formatos (`sources`) | El **conector** al ERP nuevo (API, base, export) |
| Proyecto dbt completo y sus tests | Alias de códigos, unidades base (kg, litros, m²...) | **Detectores propios del rubro** (ej. vencimientos en alimentos, estacionalidad en indumentaria) |
| Motor de reparto de gastos con sensibilidad | Canales y si sus clientes son nominales o agregados | Conceptos de gasto que no encajen en fijo / variable |
| Detectores genéricos (rentabilidad por cliente, devoluciones, clientes que se enfrían, venta cruzada, inflación vs. volumen) | Reglas de gastos: fijo / variable, canales, driver | Si el negocio **no es "vender productos a clientes"** (servicios, suscripciones), extender el modelo canónico con tablas nuevas, sin romper las existentes |
| Capa de IA: prompt, guardrails, caché, plantilla | Contexto del negocio y creencias del dueño | |
| Dashboard | Umbrales de los detectores | |

**Onboarding de un cliente nuevo:** copiar `clients/tostadero_ruta9/`, poner los archivos en `raw/`,
ajustar `client.yaml` y correr `python -m sawy build --client <nuevo>`. Si algo no encaja, los
contratos y los tests de dbt dicen exactamente qué.

**Próximo paso natural:** usar un LLM para **proponer** el `client.yaml` a partir de las columnas y
una muestra del ERP nuevo, con revisión humana y validado por los contratos. Acelera la "semana 1" de
la implementación sin poner a la IA en el camino crítico de los números.

---

## Qué dejé afuera a propósito

- **Chat sobre los datos.** El diseño lo soporta: los marts son una API natural para *tool calling*.
  Pero para Sofía, un tablero con 5 acciones claras vale más que un chat en blanco.
- **Conectores reales, autenticación, multi-tenant y programación de corridas.** Están en la tabla de producción.
- **Evals de la IA con LLM.** Hoy la calidad está asegurada por guardrails estructurales;
  el próximo paso es un set de casos.
- **Precios históricos.** El ERP solo da la lista actual; se usan los precios de cada factura.

Todos los supuestos, con su impacto, están en [ASSUMPTIONS.md](ASSUMPTIONS.md). El detalle técnico
está en [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Estructura

```
clients/tostadero_ruta9/   ← lo único específico del cliente
  client.yaml              mapeo + reglas de negocio + parámetros
  raw/                     exports del ERP (tal cual llegaron)
  ai_narrative.cache.json  textos de IA (validados) para correr sin clave
sawy/
  ingest/                  lectura genérica + contratos del modelo canónico
  transform.py             corre dbt
  insights/                KPIs + detectores → hallazgos con números
  ai/                      prompt, salida estructurada, guardrails, caché, plantilla
  report/                  gráficos (HTML/SVG) + plantilla del dashboard
dbt/                       staging → core (modelo canónico) → marts, con tests
tests/                     unitarios + pipeline completo con números de referencia
docs/index.html            dashboard publicado (GitHub Pages)
```

*Hice este trabajo con un asistente de IA como herramienta de desarrollo, como permite la consigna.
