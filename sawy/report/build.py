"""Arma el dashboard estático (un solo HTML) a partir de marts + hallazgos + narrativa."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from sawy.ai.guardrails import globalize, render
from sawy.ai.narrator import NarrativeResult
from sawy.config import ClientConfig
from sawy.insights.detectors import Context
from sawy.insights.engine import QualityNote
from sawy.insights.format import money, month_label, pct, thousands
from sawy.insights.models import InsightsReport
from sawy.report import charts
from sawy.warehouse import Warehouse

TEMPLATES = Path(__file__).parent / "templates"

# Hora de Argentina (UTC-3, sin horario de verano). Offset fijo: no depende de tzdata en la imagen.
AR_TZ = timezone(timedelta(hours=-3))

DRIVER_LABELS = {
    "base_units": "por {unit}",
    "net_amount": "por $ facturado",
    "deliveries": "por entrega",
}
DRIVER_EXPLAIN = {
    "base_units": "según los {unit} que se llevó cada uno",
    "net_amount": "según cuánta plata facturó cada uno",
    "deliveries": "según cuántas entregas (facturas) recibió cada uno",
}


def _method_label(m: str, unit: str) -> str:
    return DRIVER_LABELS[m].format(unit=unit).capitalize()


def charts_html(ctx: Context) -> dict:
    """Gráficos ya renderizados (HTML/SVG). Uno por criterio de reparto donde aplica."""
    names = ctx.product_names()
    unit = ctx.base_unit
    pnl = ctx.mart("mart_pnl_monthly").sort_values("period")
    labels = [month_label(p) for p in pnl["period"]]

    monthly = charts.columns(
        labels,
        pnl["net_result"].tolist(),
        [
            [
                f"<b>{month_label(r.period, True).capitalize()}</b>",
                f"Resultado: <b>{money(r.net_result)}</b>",
                f"Facturación: {money(r.revenue)}",
                f"Margen bruto: {money(r.gross_margin)}",
                f"Gastos variables: {money(r.variable_expenses)}",
                f"Gastos fijos: {money(r.fixed_expenses)}",
            ]
            for r in pnl.itertuples()
        ],
    )

    trend = None
    if ctx.cfg.rules.base_units_per_unit and pnl["base_quantity"].iloc[0]:
        rev_idx = (pnl["revenue"] / pnl["revenue"].iloc[0] * 100).tolist()
        vol_idx = (pnl["base_quantity"] / pnl["base_quantity"].iloc[0] * 100).tolist()
        trend = charts.lines(
            labels,
            [
                {"name": "Facturación", "values": rev_idx, "css_var": "--s1"},
                {"name": "Volumen", "values": vol_idx, "css_var": "--s2"},
            ],
            [
                [
                    f"<b>{month_label(r.period, True).capitalize()}</b>",
                    f"Facturación: {money(r.revenue)} (índice {ri:.0f})",
                    f"Volumen: {thousands(r.base_quantity)} {unit} (índice {vi:.0f})",
                ]
                for r, ri, vi in zip(pnl.itertuples(), rev_idx, vol_idx, strict=True)
            ],
        )

    ch = ctx.mart("mart_contribution_by_channel")
    pr = ctx.mart("mart_contribution_by_product")
    pr["name"] = pr["product_id"].map(names).fillna(pr["product_id"])

    def tip(name_key: str):
        return lambda r: [
            f"<b>{escape(str(r[name_key]))}</b>",  # viene del ERP: se escapa
            f"Deja: <b>{money(r['contribution'])}</b> ({pct(r['contribution_margin_pct'] or 0)} de lo vendido)",
            f"Facturación: {money(r['revenue'])}",
            f"Margen bruto: {money(r['gross_margin'])}",
            f"Gastos variables: {money(r['variable_expenses'])}",
        ]

    by_method = {}
    for m in ctx.methods:
        crow = (
            ch[ch["allocation_method"] == m].sort_values("contribution", ascending=False).to_dict("records")
        )
        prow = (
            pr[pr["allocation_method"] == m].sort_values("contribution", ascending=False).to_dict("records")
        )
        by_method[m] = {
            "label": _method_label(m, unit),
            "explain": DRIVER_EXPLAIN[m].format(unit=unit),
            "channels": charts.hbar(crow, "channel", "contribution", tip("channel")),
            "products": charts.hbar(prow, "name", "contribution", tip("name")),
            "channel_rows": [
                {
                    "name": r["channel"],
                    "revenue": money(r["revenue"]),
                    "gross_margin": money(r["gross_margin"]),
                    "variable": money(r["variable_expenses"]),
                    "contribution": money(r["contribution"]),
                    "pct": pct(r["contribution_margin_pct"] or 0),
                }
                for r in crow
            ],
            "product_rows": [
                {
                    "name": r["name"],
                    "revenue": money(r["revenue"]),
                    "contribution": money(r["contribution"]),
                    "pct": pct(r["contribution_margin_pct"] or 0),
                }
                for r in prow
            ],
        }
    return {"monthly": monthly, "trend": trend, "by_method": by_method, "default_method": ctx.default_method}


def build(
    cfg: ClientConfig,
    wh: Warehouse,
    report: InsightsReport,
    narrative: NarrativeResult,
    notes: list[QualityNote],
) -> Path:
    ctx = Context(wh=wh, cfg=cfg)
    facts = report.all_facts()
    unit = report.base_unit
    r = lambda t: render(t, facts, unit)  # noqa: E731

    n = narrative.narrative
    view_narrative = {
        "headline": r(n.headline),
        "summary": [r(s) for s in n.summary],
        "actions": [{"title": r(a.title), "why": r(a.why), "finding_ids": a.finding_ids} for a in n.actions],
        "beliefs": [
            {"belief": b.belief, "verdict": b.verdict, "explanation": r(b.explanation)} for b in n.beliefs
        ],
    }
    view_findings = [
        {
            "id": f.id,
            "severity": f.severity,
            "category": f.category,
            "kind": f.kind,
            "title": r(globalize(f.title, f.id)),
            "detail": r(globalize(f.detail, f.id)),
            "related": f.related_entities,
            "assumption": f.depends_on_assumption,
        }
        for f in report.findings
    ]
    k = report.kpis
    kpis = {
        "revenue": money(k["revenue_total"].value),
        "gross_margin": money(k["gross_margin_total"].value),
        "gross_margin_pct": pct(k["gross_margin_pct"].value),
        "variable": money(k["variable_expenses_total"].value),
        "fixed": money(k["fixed_expenses_total"].value),
        "net": money(k["net_result_total"].value),
        "net_value": k["net_result_total"].value,
        "months_negative": int(k["months_negative"].value),
        "months_total": int(k["months_total"].value),
    }
    period = (
        f"{month_label(report.period_from, True).capitalize()} a "
        f"{month_label(report.period_to, True)} {report.period_to.year}"
    )
    source_label = {
        "ai": f"Textos redactados con IA ({narrative.model})",
        "ai-cache": f"Textos redactados con IA ({narrative.model}, guardados)",
        "template": "Textos generados sin IA (plantilla)",
    }[narrative.source]

    # autoescape SIEMPRE activo: select_autoescape(["html"]) no matchea ".html.j2" y
    # dejaba sin escapar nombres del ERP y textos de la IA. Los gráficos (HTML ya
    # escapado en charts.py) son lo único que entra con |safe.
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True)
    html = env.get_template("dashboard.html.j2").render(
        client=cfg.client,
        period=period,
        reference_date=report.reference_date.strftime("%d/%m/%Y"),
        kpis=kpis,
        narrative=view_narrative,
        narrative_note=narrative.note,
        source_label=source_label,
        findings=view_findings,
        charts=charts_html(ctx),
        generated_at=datetime.now(AR_TZ).strftime("%d/%m/%Y %H:%M") + " (hora Argentina)",
        default_method_label=_method_label(report.allocation_method, unit),
        skipped=[s.model_dump() for s in report.skipped],
    )
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    out = cfg.output_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    (cfg.output_dir / "insights.json").write_text(
        json.dumps(
            {
                "report": report.model_dump(mode="json"),
                "narrative": narrative.model_dump(mode="json"),
                "data_quality": [n.model_dump() for n in notes],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return out
