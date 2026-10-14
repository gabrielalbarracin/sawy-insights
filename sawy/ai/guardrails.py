"""Guardrails de la salida del LLM.

Principio: el LLM NO escribe números. Cada cifra es un placeholder
[[clave]] que apunta a un hecho calculado por el pipeline, y lo reemplaza
código determinístico. Así una cifra mal transcripta o inventada es
imposible por construcción, y lo verificamos igual.
"""

from __future__ import annotations

import re

from sawy.ai.schema import Narrative
from sawy.insights.format import fmt
from sawy.insights.models import Fact

PLACEHOLDER = re.compile(r"\[\[\s*([A-Za-z0-9_.]+)\s*\]\]")
DIGIT = re.compile(r"\d")


def texts(n: Narrative) -> list[str]:
    out = [n.headline, *n.summary]
    for a in n.actions:
        out += [a.title, a.why]
    for b in n.beliefs:
        out += [b.explanation]  # b.belief es texto de la dueña (puede tener dígitos)
    return out


def validate(
    n: Narrative, facts: dict[str, Fact], finding_ids: set[str], allowed_names: set[str], beliefs: list[str]
) -> list[str]:
    """Devuelve la lista de errores (vacía = válida)."""
    errors: list[str] = []
    names = sorted((x for x in allowed_names if x), key=len, reverse=True)

    for t in texts(n):
        for key in PLACEHOLDER.findall(t):
            if key not in facts:
                errors.append(f"placeholder inexistente: [[{key}]]")
        stripped = PLACEHOLDER.sub("", t)
        for name in names:
            stripped = re.sub(re.escape(name), "", stripped, flags=re.IGNORECASE)
        if DIGIT.search(stripped):
            errors.append(f"hay dígitos escritos a mano (usar placeholders): «{t[:90]}»")

    if not 3 <= len(n.actions) <= 5:
        errors.append(f"se pidieron entre 3 y 5 acciones, vinieron {len(n.actions)}")
    if not 2 <= len(n.summary) <= 4:
        errors.append(f"el resumen debe tener entre 2 y 4 frases, vinieron {len(n.summary)}")
    for a in n.actions:
        bad = [i for i in a.finding_ids if i not in finding_ids]
        if bad or not a.finding_ids:
            errors.append(f"la acción «{a.title[:40]}» cita hallazgos inválidos: {bad or 'ninguno'}")
    if beliefs and len(n.beliefs) != len(beliefs):
        errors.append(f"se esperaban {len(beliefs)} creencias evaluadas, vinieron {len(n.beliefs)}")
    return errors


def render(text: str, facts: dict[str, Fact], base_unit: str) -> str:
    return PLACEHOLDER.sub(lambda m: fmt(facts[m.group(1)], base_unit) if m.group(1) in facts else "—", text)


def globalize(text: str, finding_id: str) -> str:
    """[[loss]] (local a un hallazgo) → [[F1.loss]] (clave global)."""
    return PLACEHOLDER.sub(
        lambda m: f"[[{finding_id}.{m.group(1)}]]" if "." not in m.group(1) else m.group(0), text
    )
