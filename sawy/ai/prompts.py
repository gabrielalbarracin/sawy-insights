"""Prompt del narrador. Versionado: si cambia, se invalida la caché."""

from __future__ import annotations

import json

from sawy.ai.guardrails import globalize, render
from sawy.config import ClientConfig
from sawy.insights.format import fmt
from sawy.insights.models import InsightsReport

PROMPT_VERSION = "2025-10-v1"

SYSTEM = """\
Sos analista de negocios en Sawy. Le escribís a {owner}, dueña de {client}. No es
una persona técnica: quiere saber si gana plata, con qué, y qué hacer esta semana.

Tu trabajo es REDACTAR y PRIORIZAR a partir de hallazgos ya calculados. No calculás nada.

Reglas (obligatorias):
1. NUNCA escribas números con dígitos (ni montos, ni porcentajes, ni cantidades, ni fechas).
   Toda cifra se escribe con un placeholder exacto de la lista HECHOS, por ejemplo
   [[kpi.net_result_total]] o [[F1.monthly_loss]]. Si una cifra no está en HECHOS, no la menciones.
2. Los nombres de clientes, productos y canales podés escribirlos tal cual.
3. Lenguaje simple y rioplatense (vos). Nada de jerga: en lugar de "margen de contribución"
   decí "lo que te queda después de pagar el café, el flete y el packaging".
4. Acciones: entre 3 y 5, concretas y para esta semana, empezando con un verbo. Ordenalas
   por impacto. Agrupá hallazgos del mismo tipo en una sola acción (por ejemplo, varios
   clientes que compran menos → "Llamar a ..."). Cada acción cita los IDs que la respaldan.
5. Si un hallazgo depende de un supuesto (depends_on_assumption = true), decilo con honestidad.
6. Creencias: evaluá cada creencia de la dueña con los datos (se confirma / en parte /
   no se confirma). Con tacto, sin hacerla sentir mal.
7. Directo y cálido. Sin exclamaciones ni emojis.
"""


def build_messages(report: InsightsReport, cfg: ClientConfig) -> list[dict]:
    facts = report.all_facts()
    unit = report.base_unit
    payload = {
        "negocio": cfg.client.business_context.strip(),
        "periodo": f"{report.period_from:%m/%Y} a {report.period_to:%m/%Y}",
        "creencias_de_la_duena": cfg.client.owner_beliefs,
        "HECHOS": {k: {"significa": f.label, "valor": fmt(f, unit)} for k, f in facts.items()},
        "hallazgos": [
            {
                "id": f.id,
                "tipo": f.kind,
                "categoria": f.category,
                "severidad": f.severity,
                "depends_on_assumption": f.depends_on_assumption,
                "titulo": render(globalize(f.title, f.id), facts, unit),
                "detalle": render(globalize(f.detail, f.id), facts, unit),
                "entidades_relacionadas": f.related_entities[:20],
            }
            for f in report.findings
        ],
    }
    owner = cfg.client.owner_name or "la dueña"
    return [
        {"role": "system", "content": SYSTEM.format(owner=owner, client=cfg.client.name)},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=1)},
    ]
