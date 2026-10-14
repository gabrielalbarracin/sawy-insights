"""Proveedores de LLM.

Gemini (y otros) exponen una API compatible con la de OpenAI, así que se usa
un solo SDK (`openai`) cambiando `base_url`. Sumar un proveedor = una entrada
en PROVIDERS. El resto (prompt, schema, guardrails, caché) no cambia.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

from sawy.ai.schema import Narrative, strict_json_schema

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    key_env: str
    default_model: str
    base_url: str | None = None


PROVIDERS: dict[str, ProviderSpec] = {
    "gemini": ProviderSpec(
        name="gemini",
        key_env="GEMINI_API_KEY",
        default_model="gemini-3.8-flash",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    ),
    "openai": ProviderSpec(name="openai", key_env="OPENAI_API_KEY", default_model="gpt-4.1-mini"),
}


@dataclass(frozen=True)
class LLMConfig:
    provider: ProviderSpec
    api_key: str
    model: str


def resolve() -> LLMConfig | None:
    """Elige proveedor: LLM_PROVIDER explícito, o el primero que tenga clave cargada."""
    wanted = os.getenv("LLM_PROVIDER", "").strip().lower()
    if wanted and wanted not in PROVIDERS:
        raise ValueError(f"LLM_PROVIDER='{wanted}' no existe. Opciones: {sorted(PROVIDERS)}")
    candidates = [PROVIDERS[wanted]] if wanted else list(PROVIDERS.values())
    for spec in candidates:
        key = os.getenv(spec.key_env, "").strip()
        if key:
            model = os.getenv("LLM_MODEL", "").strip() or spec.default_model
            return LLMConfig(provider=spec, api_key=key, model=model)
    return None


def complete(cfg: LLMConfig, messages: list[dict]) -> Narrative:
    """Pide la narrativa con salida estructurada.

    Primero intenta JSON Schema estricto. Si el proveedor no lo acepta (las
    APIs "compatibles" no siempre soportan todo), cae a modo JSON con el
    schema en el prompt. En ambos casos la salida se valida igual después.
    """
    from openai import BadRequestError, OpenAI  # import diferido: solo si hay clave

    client = OpenAI(api_key=cfg.api_key, base_url=cfg.provider.base_url, timeout=120, max_retries=2)
    schema = strict_json_schema()
    try:
        resp = client.chat.completions.create(
            model=cfg.model,
            messages=messages,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "narrative", "strict": True, "schema": schema},
            },
        )
    except BadRequestError as exc:
        log.warning("%s no aceptó json_schema (%s); se usa modo JSON", cfg.provider.name, exc)
        hint = {
            "role": "system",
            "content": "Respondé SOLO con un objeto JSON válido que cumpla este JSON Schema:\n"
            + json.dumps(schema, ensure_ascii=False),
        }
        resp = client.chat.completions.create(
            model=cfg.model, messages=[*messages, hint], response_format={"type": "json_object"}
        )
    content = resp.choices[0].message.content or "{}"
    return Narrative.model_validate_json(_strip_fences(content))


def _strip_fences(text: str) -> str:
    """Algunos modelos envuelven el JSON en ```json ... ```."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    return t.strip()
