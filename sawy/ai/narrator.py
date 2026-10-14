"""Narrativa del dashboard: IA con caché, validación y modo sin IA.

Orden de preferencia:
  1. Caché válida (mismos hechos + misma versión de prompt) → no llama a la API.
  2. Hay clave de un proveedor (GEMINI_API_KEY u OPENAI_API_KEY) → genera,
     valida y reintenta una vez con los errores.
  3. Sin clave o si la IA falla → plantilla determinística (el dashboard nunca se rompe).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from sawy.ai import guardrails, providers
from sawy.ai.prompts import PROMPT_VERSION, build_messages
from sawy.ai.schema import Action, Narrative
from sawy.config import ClientConfig
from sawy.insights.models import InsightsReport

log = logging.getLogger(__name__)


class NarrativeResult(BaseModel):
    narrative: Narrative  # con placeholders (se renderiza en el dashboard)
    source: str  # "ai" | "ai-cache" | "template"
    model: str | None = None
    generated_at: str | None = None
    note: str | None = None  # por qué se usó la plantilla, si aplica


# --------------------------------------------------------------------------- #
def _cache_key(report: InsightsReport) -> str:
    facts = {k: round(v.value, 2) for k, v in report.all_facts().items()}
    ids = [(f.id, f.key) for f in report.findings]
    blob = json.dumps({"v": PROMPT_VERSION, "facts": facts, "ids": ids}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _cache_path(cfg: ClientConfig) -> Path:
    return cfg.base_dir / "ai_narrative.cache.json"


def _validate(n: Narrative, report: InsightsReport, cfg: ClientConfig) -> list[str]:
    return guardrails.validate(
        n,
        facts=report.all_facts(),
        finding_ids={f.id for f in report.findings},
        allowed_names=report.allowed_names(),
        beliefs=cfg.client.owner_beliefs,
    )


# --------------------------------------------------------------------------- #
def _generate(report: InsightsReport, cfg: ClientConfig, llm: providers.LLMConfig) -> Narrative:
    messages = build_messages(report, cfg)
    for attempt in (1, 2):
        narrative = providers.complete(llm, messages)
        errors = _validate(narrative, report, cfg)
        if not errors:
            return narrative
        log.warning("Salida de IA inválida (intento %s): %s", attempt, errors)
        messages += [
            {"role": "assistant", "content": narrative.model_dump_json()},
            {
                "role": "user",
                "content": "Corregí estos problemas y devolvé todo de nuevo:\n- " + "\n- ".join(errors),
            },
        ]
    raise ValueError(f"La IA no cumplió las reglas tras 2 intentos: {errors}")


# --------------------------------------------------------------------------- #
def template_narrative(report: InsightsReport) -> Narrative:
    """Versión determinística: misma estructura, sin IA."""
    k = report.kpis
    losing = k["net_result_total"].value < 0
    headline = (
        "Hoy el negocio pierde plata: en [[kpi.months_total]] meses el resultado fue "
        "[[kpi.net_result_total]], con [[kpi.months_negative]] meses en rojo."
        if losing
        else "El negocio gana plata: en [[kpi.months_total]] meses el resultado fue [[kpi.net_result_total]]."
    )
    diag = [f for f in report.findings if f.category == "diagnostico"]
    acts = [f for f in report.findings if f.category == "accion"]
    summary = [guardrails.globalize(f.title, f.id) for f in diag[:2]]
    summary += [guardrails.globalize(f.title, f.id) for f in acts[:2]]
    summary = summary[:4] or ["No se detectaron hallazgos relevantes."]

    actions: list[Action] = []
    seen: dict[str, Action] = {}
    for f in acts:
        if f.kind in seen:  # agrupa hallazgos del mismo tipo
            seen[f.kind].finding_ids.append(f.id)
            continue
        a = Action(
            title=guardrails.globalize(f.title, f.id),
            why=guardrails.globalize(f.detail, f.id),
            finding_ids=[f.id],
        )
        seen[f.kind] = a
        actions.append(a)
    return Narrative(headline=headline, summary=summary, actions=actions[:5], beliefs=[])


def narrate(report: InsightsReport, cfg: ClientConfig, refresh: bool = False) -> NarrativeResult:
    key = _cache_key(report)
    cache_file = _cache_path(cfg)
    llm = providers.resolve()

    if cache_file.exists() and not refresh:
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if cached.get("key") == key:
                n = Narrative.model_validate(cached["narrative"])
                if not _validate(n, report, cfg):
                    log.info("Narrativa de IA tomada de la caché (%s)", cached.get("model"))
                    return NarrativeResult(
                        narrative=n,
                        source="ai-cache",
                        model=cached.get("model"),
                        generated_at=cached.get("generated_at"),
                    )
        except Exception:  # caché corrupta: se ignora
            log.warning("Caché de IA inválida, se ignora")

    if llm is None:
        return NarrativeResult(
            narrative=template_narrative(report),
            source="template",
            note="Sin clave de IA (GEMINI_API_KEY u OPENAI_API_KEY): textos generados con plantilla.",
        )
    model = f"{llm.provider.name}/{llm.model}"
    log.info("Generando narrativa con %s", model)
    try:
        n = _generate(report, cfg, llm)
    except Exception as exc:
        log.error("Falló la generación con IA, se usa la plantilla: %s", exc)
        return NarrativeResult(
            narrative=template_narrative(report),
            source="template",
            note=f"La IA no respondió correctamente ({type(exc).__name__}); se usó la plantilla.",
        )

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cache_file.write_text(
        json.dumps(
            {
                "key": key,
                "model": model,
                "prompt_version": PROMPT_VERSION,
                "generated_at": now,
                "narrative": n.model_dump(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return NarrativeResult(narrative=n, source="ai", model=model, generated_at=now)
