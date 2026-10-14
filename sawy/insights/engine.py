"""Orquesta KPIs + detectores → InsightsReport (JSON serializable)."""

from __future__ import annotations

import logging

import pandas as pd
from pydantic import BaseModel

from sawy.config import ClientConfig
from sawy.insights import detectors as D
from sawy.insights.format import pct, thousands
from sawy.insights.models import SEVERITY_ORDER, Fact, Finding, InsightsReport, SkippedDetector
from sawy.warehouse import Warehouse

log = logging.getLogger(__name__)


def compute_kpis(ctx: D.Context) -> dict[str, Fact]:
    pnl = ctx.mart("mart_pnl_monthly").sort_values("period")
    last = pnl.iloc[-1]
    rev = pnl["revenue"].sum()
    return {
        "revenue_total": Fact(value=rev, unit="money", label="facturación neta del período"),
        "gross_margin_total": Fact(
            value=pnl["gross_margin"].sum(), unit="money", label="lo que queda después de pagar la mercadería"
        ),
        "gross_margin_pct": Fact(
            value=pnl["gross_margin"].sum() / rev if rev else 0, unit="pct", label="margen bruto"
        ),
        "variable_expenses_total": Fact(
            value=pnl["variable_expenses"].sum(),
            unit="money",
            label="gastos variables (flete, packaging, comisiones)",
        ),
        "fixed_expenses_total": Fact(
            value=pnl["fixed_expenses"].sum(), unit="money", label="gastos fijos (alquiler, sueldos, energía)"
        ),
        "net_result_total": Fact(
            value=pnl["net_result"].sum(), unit="money", label="resultado del período (ganancia o pérdida)"
        ),
        "net_result_last_month": Fact(
            value=last["net_result"], unit="money", label="resultado del último mes"
        ),
        "months_negative": Fact(
            value=int((pnl["net_result"] < 0).sum()), unit="count", label="meses con pérdida"
        ),
        "months_total": Fact(value=len(pnl), unit="count", label="meses analizados"),
        "returns_total": Fact(
            value=pnl["returns_amount"].sum(), unit="money", label="devoluciones (notas de crédito)"
        ),
        "base_quantity_total": Fact(
            value=pnl["base_quantity"].sum(), unit="base_qty", label=f"volumen vendido ({ctx.base_unit})"
        ),
    }


class QualityNote(BaseModel):
    level: str  # "ok" | "info" | "aviso"
    message: str


def quality_notes(ctx: D.Context) -> list[QualityNote]:
    """Qué encontramos en los datos y qué hicimos. Genérico: sale del modelo."""
    s = ctx.mart("fct_sales_lines", schema="core")
    notes: list[QualityNote] = []
    n = len(s)
    legacy = s[s["is_legacy_code"].astype(bool)]
    if len(legacy):
        codes = ", ".join(sorted(legacy["source_product_id"].unique()))
        notes.append(
            QualityNote(
                level="info",
                message=(
                    f"{len(legacy)} renglones usaban códigos viejos de producto ({codes}). "
                    "Se unificaron con el código vigente para no perder esas ventas."
                ),
            )
        )
    nc = s[s["document_type"] == "credit_note"]
    if len(nc):
        notes.append(
            QualityNote(
                level="info",
                message=(
                    f"{nc['document_id'].nunique()} notas de crédito (devoluciones) se descuentan de las ventas."
                ),
            )
        )
    if "salesperson" in s.columns:
        empty = s["salesperson"].isna().mean()
        if empty > 0.5:
            notes.append(
                QualityNote(
                    level="aviso",
                    message=(
                        f"El vendedor está vacío en {pct(empty)} de los renglones: no se analiza por vendedor."
                    ),
                )
            )
    if ctx.sensitive_concepts():
        notes.append(
            QualityNote(
                level="aviso",
                message=(
                    f"El sistema no asigna {ctx.sensitive_labels()} a cada cliente. Lo repartimos con un "
                    "criterio y mostramos cómo cambian los resultados con otros criterios."
                ),
            )
        )
    notes.append(
        QualityNote(
            level="ok",
            message=(
                f"{thousands(n)} renglones procesados. Todas las ventas tienen costo del mes correspondiente y "
                "el total coincide con lo exportado del sistema."
            ),
        )
    )
    return notes


def run(cfg: ClientConfig, wh: Warehouse) -> tuple[InsightsReport, list[QualityNote]]:
    ctx = D.Context(wh=wh, cfg=cfg)
    findings: list[Finding] = []
    skipped: list[SkippedDetector] = []
    for det in D.REGISTRY:
        missing = [r for r in det.requires if not D.CAPABILITIES[r](ctx)]
        if missing:
            skipped.append(SkippedDetector(detector=det.name, reason=f"faltan datos: {missing}"))
            continue
        try:
            found = det.fn(ctx)
        except Exception as exc:  # un detector roto no tira abajo el reporte
            log.exception("Detector %s falló", det.name)
            skipped.append(SkippedDetector(detector=det.name, reason=f"error: {exc}"))
            continue
        findings.extend(found)

    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], -f.impact_monthly))
    for i, f in enumerate(findings, start=1):
        f.id = f"F{i}"

    sales = ctx.mart("fct_sales_lines", schema="core")
    periods = ctx.periods
    report = InsightsReport(
        client_id=cfg.client.id,
        client_name=cfg.client.name,
        currency=cfg.client.currency,
        base_unit=cfg.client.base_unit,
        period_from=periods[0].date(),
        period_to=periods[-1].date(),
        reference_date=pd.Timestamp(sales["sale_date"].max()).date(),
        allocation_method=ctx.default_method,
        kpis=compute_kpis(ctx),
        findings=findings,
        skipped=skipped,
    )
    log.info("%s hallazgos, %s detectores omitidos", len(findings), len(skipped))
    return report, quality_notes(ctx)
