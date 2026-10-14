"""Contrato de los hallazgos.

Un hallazgo es la unidad de conocimiento entre el análisis determinístico y
la IA: trae los NÚMEROS ya calculados (facts) y un texto base. La IA solo
puede redactar y priorizar sobre esto; nunca calcula.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

Unit = Literal["money", "pct", "base_qty", "count", "rate", "days"]
Severity = Literal["alta", "media", "baja"]
Category = Literal["accion", "diagnostico"]

SEVERITY_ORDER = {"alta": 0, "media": 1, "baja": 2}


class Fact(BaseModel):
    value: float
    unit: Unit
    label: str  # descripción para la IA ("pérdida mensual promedio")


class Finding(BaseModel):
    id: str = ""  # F1, F2... (se asigna al rankear)
    key: str  # estable: "loss_making_customer:C0001"
    kind: str
    category: Category
    severity: Severity
    title: str  # puede usar [[fact]] como placeholder
    detail: str  # texto base / fallback, con [[fact]]
    entity_type: str | None = None
    entity_id: str | None = None
    entity_name: str | None = None
    related_entities: list[str] = Field(default_factory=list)  # nombres (ej. clientes a llamar)
    facts: dict[str, Fact] = Field(default_factory=dict)
    impact_monthly: float = 0.0  # $ por mes, para priorizar
    depends_on_assumption: bool = False


class SkippedDetector(BaseModel):
    detector: str
    reason: str


class InsightsReport(BaseModel):
    client_id: str
    client_name: str
    currency: str
    base_unit: str
    period_from: date
    period_to: date
    reference_date: date  # último día con ventas
    allocation_method: str  # criterio por defecto
    kpis: dict[str, Fact]
    findings: list[Finding]
    skipped: list[SkippedDetector] = Field(default_factory=list)

    def all_facts(self) -> dict[str, Fact]:
        """Diccionario global de hechos: kpi.* y F<n>.* — lo único citable."""
        out = {f"kpi.{k}": v for k, v in self.kpis.items()}
        for f in self.findings:
            out.update({f"{f.id}.{k}": v for k, v in f.facts.items()})
        return out

    def allowed_names(self) -> set[str]:
        """Textos que pueden aparecer literalmente (nombres con dígitos, ej. 'Blend Casa 1 kg')."""
        names = {self.client_name}
        for f in self.findings:
            if f.entity_name:
                names.add(f.entity_name)
            names.update(f.related_entities)
        return names
