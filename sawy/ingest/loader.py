"""Ingesta genérica: archivos del ERP → tablas canónicas en el schema `landing`.

Solo resuelve lo ESTRUCTURAL (nombres de columnas, formatos, tipos, signos).
Lo SEMÁNTICO (alias de códigos, unidades, canales, reparto de gastos) viaja
como tablas de reglas y se aplica en dbt, a la vista y testeado.
"""

from __future__ import annotations

import logging

import pandas as pd

from sawy.config import ClientConfig, SourceSpec
from sawy.ingest.contracts import CONTRACTS, ContractError, TableContract, validate
from sawy.warehouse import Warehouse

log = logging.getLogger(__name__)

LANDING = "landing"


# --------------------------------------------------------------------------- #
# Lectura y tipado
# --------------------------------------------------------------------------- #
def _read_raw(cfg: ClientConfig, spec: SourceSpec) -> pd.DataFrame:
    path = cfg.base_dir / spec.file
    if not path.exists():
        raise FileNotFoundError(f"No se encontró {path}")
    df = pd.read_csv(
        path,
        sep=spec.format.sep,
        encoding=spec.format.encoding,
        dtype=str,
        keep_default_na=False,
    )
    df.columns = [c.strip() for c in df.columns]
    missing = [src for src in spec.columns.values() if src not in df.columns]
    if missing:
        raise ContractError(
            f"{spec.file}: el mapeo pide columnas que no están en el archivo: {missing}. "
            f"Columnas disponibles: {list(df.columns)}"
        )
    return df.rename(columns={src: canon for canon, src in spec.columns.items()})[list(spec.columns.keys())]


def _as_str(s: pd.Series) -> pd.Series:
    s = s.astype("string").str.strip()
    return s.mask(s == "", pd.NA)


def _as_float(s: pd.Series, decimal: str) -> pd.Series:
    s = _as_str(s)
    if decimal == ",":
        s = s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors="coerce")


def _cast(df: pd.DataFrame, contract: TableContract, spec: SourceSpec, source: str) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    problems: list[str] = []
    for name, col in contract.columns.items():
        if name in contract.derived:
            continue
        if name not in df.columns:  # columna opcional no mapeada
            out[name] = pd.NA
            continue
        raw = _as_str(df[name])
        if col.dtype == "str":
            out[name] = raw
        elif col.dtype in ("float", "int"):
            out[name] = _as_float(raw, spec.format.decimal)
        elif col.dtype == "date":
            fmt = spec.format.period_format if name == "period" else spec.format.date_format
            parsed = pd.to_datetime(raw, format=fmt, errors="coerce")
            out[name] = parsed.dt.to_period("M").dt.to_timestamp() if name == "period" else parsed
        elif col.dtype == "bool":
            mapping = spec.boolean_values or {"true": True, "false": False}
            out[name] = raw.map(mapping)
        bad = raw.notna() & out[name].isna()
        if bad.any():
            examples = raw[bad].head(3).tolist()
            problems.append(f"'{name}': {int(bad.sum())} valores no interpretables, ej. {examples}")
    if problems:
        raise ContractError(f"[{contract.name}] {source}:\n  - " + "\n  - ".join(problems))
    return out


# --------------------------------------------------------------------------- #
# Normalizaciones específicas por tabla (siguen siendo genéricas)
# --------------------------------------------------------------------------- #
def _normalize_sales(df: pd.DataFrame, raw: pd.DataFrame, spec: SourceSpec) -> pd.DataFrame:
    if not spec.document_types:
        raise ContractError("sales_lines: falta 'document_types' (qué es factura y qué es NC)")
    doc_raw = _as_str(raw["document_type"])
    unknown = sorted(set(doc_raw.dropna()) - set(spec.document_types))
    if unknown:
        raise ContractError(f"sales_lines: tipos de comprobante sin mapear: {unknown}")
    df["document_type"] = doc_raw.map(spec.document_types)

    # Convención canónica: las notas de crédito restan (cantidad e importe negativos).
    is_nc = df["document_type"] == "credit_note"
    if spec.credit_note_sign == "positive":
        df.loc[is_nc, ["quantity", "net_amount"]] *= -1
    wrong_sign = is_nc & ((df["net_amount"] > 0) | (df["quantity"] > 0))
    if wrong_sign.any():
        raise ContractError(
            f"sales_lines: {int(wrong_sign.sum())} notas de crédito quedaron con signo positivo. "
            "Revisar 'credit_note_sign' en client.yaml."
        )

    df.insert(0, "line_id", range(1, len(df) + 1))
    df["period"] = df["sale_date"].dt.to_period("M").dt.to_timestamp()
    return df


def load_table(cfg: ClientConfig, name: str) -> pd.DataFrame:
    spec: SourceSpec = getattr(cfg.sources, name)
    contract = CONTRACTS[name]
    raw = _read_raw(cfg, spec)
    df = _cast(raw, contract, spec, spec.file)
    if name == "sales_lines":
        df = _normalize_sales(df, raw, spec)
    df = df[list(contract.columns)]
    validate(df, contract, spec.file)
    return _to_plain_dtypes(df, contract)


def _to_plain_dtypes(df: pd.DataFrame, contract: TableContract) -> pd.DataFrame:
    """Tipos numpy/objeto simples: cualquier motor los lee igual (sin extension dtypes)."""
    out = df.copy()
    for name, col in contract.columns.items():
        s = out[name]
        if col.dtype == "float":
            out[name] = pd.to_numeric(s, errors="coerce").astype("float64")
        elif col.dtype == "int":
            out[name] = s.astype("int64")
        elif col.dtype in ("str", "bool"):
            out[name] = s.astype(object).where(s.notna(), None)
    return out


# --------------------------------------------------------------------------- #
# Reglas de negocio → tablas (para que dbt las aplique)
# --------------------------------------------------------------------------- #
def rule_tables(cfg: ClientConfig) -> dict[str, pd.DataFrame]:
    r = cfg.rules
    a = cfg.analysis
    return {
        "rule_product_alias": pd.DataFrame(
            list(r.product_aliases.items()), columns=["source_product_id", "product_id"]
        ),
        "rule_product_units": pd.DataFrame(
            list(r.base_units_per_unit.items()), columns=["product_id", "base_units_per_unit"]
        ).astype({"base_units_per_unit": "float64"}),
        "rule_channel": pd.DataFrame(
            [c.model_dump() for c in r.channels], columns=["segment", "channel", "named_customers"]
        ),
        "rule_expense": pd.DataFrame(
            [
                {
                    "concept": e.concept,
                    "behavior": e.behavior,
                    "driver": e.driver or "",
                    "is_sensitive": bool(e.sensitive),
                }
                for e in r.expenses
            ],
            columns=["concept", "behavior", "driver", "is_sensitive"],
        ),
        "rule_expense_scope": pd.DataFrame(
            [{"concept": e.concept, "channel": ch} for e in r.expenses for ch in e.channels],
            columns=["concept", "channel"],
        ),
        "cfg_allocation_methods": pd.DataFrame(
            [{"method": m, "is_default": m == a.default_allocation_method} for m in a.allocation_methods],
            columns=["method", "is_default"],
        ),
    }


RULE_TYPES: dict[str, dict[str, str]] = {
    "rule_product_alias": {"source_product_id": "VARCHAR", "product_id": "VARCHAR"},
    "rule_product_units": {"product_id": "VARCHAR", "base_units_per_unit": "DOUBLE"},
    "rule_channel": {"segment": "VARCHAR", "channel": "VARCHAR", "named_customers": "BOOLEAN"},
    "rule_expense": {
        "concept": "VARCHAR",
        "behavior": "VARCHAR",
        "driver": "VARCHAR",
        "is_sensitive": "BOOLEAN",
    },
    "rule_expense_scope": {"concept": "VARCHAR", "channel": "VARCHAR"},
    "cfg_allocation_methods": {"method": "VARCHAR", "is_default": "BOOLEAN"},
}


def run(cfg: ClientConfig, wh: Warehouse) -> dict[str, int]:
    """Carga todo al schema landing. Devuelve filas por tabla."""
    counts: dict[str, int] = {}
    for name, contract in CONTRACTS.items():
        df = load_table(cfg, name)
        wh.write_df(LANDING, name, df, column_types=contract.sql_types)
        counts[name] = len(df)
        log.info("landing.%s: %s filas", name, len(df))
    for name, df in rule_tables(cfg).items():
        wh.write_df(LANDING, name, df, column_types=RULE_TYPES[name])
        counts[name] = len(df)
    return counts
