"""Formato de números para una persona no técnica (es-AR)."""

from __future__ import annotations

from sawy.insights.models import Fact

MONTHS_ES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
MONTHS_ES_LONG = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]


def thousands(n: float, decimals: int = 0) -> str:
    s = f"{abs(n):,.{decimals}f}"  # 1,234,567.8
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def money(v: float, short: bool = True) -> str:
    sign = "−" if v < 0 else ""
    a = abs(v)
    if short and a >= 1_000_000:
        return f"{sign}${thousands(a / 1_000_000, 1)} M"
    return f"{sign}${thousands(a)}"


def pct(v: float) -> str:
    p = v * 100
    decimals = 1 if 0 < abs(p) < 10 and round(abs(p), 1) != round(abs(p)) else 0
    return f"{'−' if p < 0 else ''}{thousands(p, decimals)}%"


def fmt(f: Fact, base_unit: str = "unidades") -> str:
    if f.unit == "money":
        return money(f.value)
    if f.unit == "pct":
        return pct(f.value)
    if f.unit == "base_qty":
        return f"{thousands(f.value)} {base_unit}"
    if f.unit == "rate":
        return thousands(f.value, 1)
    if f.unit == "days":
        return f"{thousands(f.value)} días"
    return thousands(f.value)


def month_label(d, long: bool = False) -> str:
    names = MONTHS_ES_LONG if long else MONTHS_ES
    return names[d.month - 1]
