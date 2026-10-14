"""Salida estructurada que se le pide al LLM."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Action(_Strict):
    title: str = Field(description="Acción concreta para esta semana, empieza con verbo. Máx. 10 palabras.")
    why: str = Field(description="Por qué, en 1 o 2 oraciones simples. Cifras SOLO con [[placeholders]].")
    finding_ids: list[str] = Field(description="IDs de hallazgos que la respaldan, ej. ['F1'].")


class BeliefCheck(_Strict):
    belief: str = Field(description="La creencia de la dueña, tal cual se la pasó.")
    verdict: Literal["se confirma", "en parte", "no se confirma"]
    explanation: str = Field(description="1 o 2 oraciones con tacto. Cifras SOLO con [[placeholders]].")


class Narrative(_Strict):
    headline: str = Field(description="Respuesta directa a '¿estoy ganando plata?'. Una oración.")
    summary: list[str] = Field(description="2 a 4 frases: con qué gana, con qué pierde, qué mirar.")
    actions: list[Action] = Field(description="3 a 5 acciones para esta semana, ordenadas por impacto.")
    beliefs: list[BeliefCheck] = Field(description="Una por cada creencia de la dueña.")


def strict_json_schema() -> dict:
    """JSON Schema compatible con 'strict' de OpenAI (todo required, sin extras)."""

    def fix(node: dict) -> dict:
        if node.get("type") == "object" and "properties" in node:
            node["required"] = list(node["properties"].keys())
            node["additionalProperties"] = False
            for p in node["properties"].values():
                fix(p)
        if node.get("type") == "array" and isinstance(node.get("items"), dict):
            fix(node["items"])
        for d in node.get("$defs", {}).values():
            fix(d)
        node.pop("title", None)
        for p in node.get("properties", {}).values():
            p.pop("title", None)
        return node

    return fix(Narrative.model_json_schema())
