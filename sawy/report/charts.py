"""Gráficos como HTML/SVG generados en Python.

Sin librerías de JS ni CDN: el dashboard funciona offline, se testea en
Python y escala bien en el celular (las etiquetas son HTML, no texto dentro
de un SVG que se achica). Colores por variables CSS → modo claro/oscuro.
Cada marca lleva `data-tip` (tooltip) y es enfocable con teclado.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from html import escape

from sawy.insights.format import money


def _nice_ticks(lo: float, hi: float, n: int = 4) -> list[float]:
    lo, hi = min(lo, 0.0), max(hi, 0.0)
    if hi == lo:
        return [lo]
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    start = math.floor(lo / step) * step
    ticks, t = [], start
    while t <= hi + step * 0.001:
        ticks.append(round(t, 6))
        t += step
    if ticks[-1] < hi:
        ticks.append(ticks[-1] + step)
    return ticks


def axis_money(v: float) -> str:
    if v == 0:
        return "$0"
    sign = "−" if v < 0 else ""
    a = abs(v)
    if a >= 1_000_000:
        s = f"{a / 1_000_000:.1f}".replace(".", ",").replace(",0", "")
        return f"{sign}${s} M"
    return f"{sign}${a / 1000:.0f} mil"


def _tip(lines: list[str]) -> str:
    return escape("<br>".join(lines), quote=True)


# --------------------------------------------------------------------------- #
def hbar(rows: list[dict], label: str, value: str, tip: Callable[[dict], list[str]]) -> str:
    """Barras horizontales con polaridad (gana / pierde) y línea de cero."""
    if not rows:
        return '<p class="note">Sin datos.</p>'
    vals = [r[value] for r in rows]
    lo, hi = min(0.0, *vals), max(0.0, *vals)
    rng = (hi - lo) or 1.0
    zero = -lo / rng * 100
    out = ['<div class="hb">']
    for r in rows:
        v = r[value]
        w = abs(v) / rng * 100
        left = zero if v >= 0 else zero - w
        cls = "pos" if v >= 0 else "neg"
        out.append(
            f'<div class="hb-row" tabindex="0" data-tip="{_tip(tip(r))}">'
            f'<div class="hb-label" title="{escape(str(r[label]))}">{escape(str(r[label]))}</div>'
            f'<div class="hb-track"><span class="hb-zero" style="left:{zero:.2f}%"></span>'
            f'<span class="hb-bar {cls}" style="left:{left:.2f}%;width:{max(w, 0.4):.2f}%"></span></div>'
            f'<div class="hb-val">{escape(money(v))}</div></div>'
        )
    out.append("</div>")
    return "".join(out)


# --------------------------------------------------------------------------- #
def columns(labels: list[str], values: list[float], tips: list[list[str]], height: int = 220) -> str:
    """Columnas con polaridad sobre una línea de cero, con eje y de valores redondos."""
    ticks = _nice_ticks(min(values), max(values))
    lo, hi = ticks[0], ticks[-1]
    rng = (hi - lo) or 1.0
    top = lambda v: (hi - v) / rng * 100  # noqa: E731
    out = [f'<div class="col-chart" style="height:{height}px"><div class="col-plot">']
    for t in ticks:
        cls = "gl zero" if t == 0 else "gl"
        out.append(f'<div class="{cls}" style="top:{top(t):.2f}%"><span>{escape(axis_money(t))}</span></div>')
    out.append('<div class="cols">')
    for v, tp in zip(values, tips, strict=True):
        y0, y1 = top(max(v, 0)), top(min(v, 0))
        cls = "pos" if v >= 0 else "neg"
        out.append(
            f'<div class="col" tabindex="0" data-tip="{_tip(tp)}">'
            f'<span class="col-bar {cls}" style="top:{y0:.2f}%;height:{max(y1 - y0, 0.5):.2f}%"></span></div>'
        )
    out.append("</div></div>")
    out.append(
        '<div class="col-x">' + "".join(f"<span>{escape(lab)}</span>" for lab in labels) + "</div></div>"
    )
    return "".join(out)


# --------------------------------------------------------------------------- #
def lines(labels: list[str], series: list[dict], tips: list[list[str]], height: int = 240) -> str:
    """Líneas sobre un solo eje. series = [{name, values, css_var}]."""
    allv = [v for s in series for v in s["values"] if v is not None]
    pad = (max(allv) - min(allv)) * 0.15 or 5
    lo, hi = min(allv) - pad, max(allv) + pad
    rng = hi - lo
    n = len(labels)
    x = lambda i: (i / (n - 1) * 100) if n > 1 else 50  # noqa: E731
    y = lambda v: (hi - v) / rng * 100  # noqa: E731
    step = 5 if rng < 40 else 10
    ticks = [t for t in range(int(math.ceil(lo / step) * step), int(hi) + 1, step)]

    out = [f'<div class="ln-chart" style="height:{height}px"><div class="ln-plot">']
    for t in ticks:
        out.append(f'<div class="gl" style="top:{y(t):.2f}%"><span>{t}</span></div>')
    out.append('<svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">')
    for s in series:
        pts = " ".join(f"{x(i):.2f},{y(v):.2f}" for i, v in enumerate(s["values"]) if v is not None)
        out.append(
            f'<polyline points="{pts}" fill="none" stroke="var({s["css_var"]})" '
            'stroke-width="2" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>'
        )
    out.append("</svg>")
    for s in series:
        for i, v in enumerate(s["values"]):
            if v is None:
                continue
            out.append(
                f'<span class="ln-dot" tabindex="0" style="left:{x(i):.2f}%;top:{y(v):.2f}%;'
                f'background:var({s["css_var"]})" data-tip="{_tip(tips[i])}"></span>'
            )
        last = s["values"][-1]
        out.append(f'<span class="ln-end" style="top:{y(last):.2f}%">{escape(s["name"])} {last:.0f}</span>')
    out.append("</div>")
    out.append(
        '<div class="col-x ln-x">' + "".join(f"<span>{escape(lab)}</span>" for lab in labels) + "</div></div>"
    )
    return "".join(out)
