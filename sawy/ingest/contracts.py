"""Contratos del modelo canónico.

Es la frontera entre "lo que manda cada ERP" y "lo que el resto del sistema
asume". Si un archivo no cumple, se corta acá con un mensaje accionable.
Se valida de forma vectorizada (pandas), no fila por fila, para escalar a
millones de renglones sin cambios.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

DType = Literal["str", "float", "int", "date", "bool"]
SQL_TYPES = {"str": "VARCHAR", "float": "DOUBLE", "int": "BIGINT", "date": "DATE", "bool": "BOOLEAN"}


@dataclass(frozen=True)
class Col:
    dtype: DType
    required: bool = True
    allowed: frozenset[str] | None = None


@dataclass(frozen=True)
class TableContract:
    name: str
    columns: dict[str, Col]
    primary_key: tuple[str, ...]
    derived: frozenset[str] = field(default_factory=frozenset)  # las agrega el loader

    @property
    def sql_types(self) -> dict[str, str]:
        return {c: SQL_TYPES[spec.dtype] for c, spec in self.columns.items()}


SALES_LINES = TableContract(
    name="sales_lines",
    columns={
        "line_id": Col("int"),
        "sale_date": Col("date"),
        "period": Col("date"),
        "document_id": Col("str"),
        "document_type": Col("str", allowed=frozenset({"invoice", "credit_note"})),
        "customer_id": Col("str"),
        "product_id": Col("str"),
        "quantity": Col("float"),
        "unit_price": Col("float", required=False),
        "discount_pct": Col("float", required=False),
        "net_amount": Col("float"),
        "salesperson": Col("str", required=False),
    },
    primary_key=("line_id",),
    derived=frozenset({"line_id", "period"}),
)

PRODUCTS = TableContract(
    name="products",
    columns={
        "product_id": Col("str"),
        "product_name": Col("str"),
        "unit_of_measure": Col("str", required=False),
        "category": Col("str", required=False),
        "list_price": Col("float", required=False),
        "is_active": Col("bool", required=False),
    },
    primary_key=("product_id",),
)

CUSTOMERS = TableContract(
    name="customers",
    columns={
        "customer_id": Col("str"),
        "customer_name": Col("str"),
        "segment": Col("str"),
        "discount_pct": Col("float", required=False),
        "tax_id": Col("str", required=False),
        "city": Col("str", required=False),
    },
    primary_key=("customer_id",),
)

PRODUCT_COSTS = TableContract(
    name="product_costs",
    columns={
        "product_id": Col("str"),
        "period": Col("date"),
        "unit_cost": Col("float"),
        "currency": Col("str", required=False),
    },
    primary_key=("product_id", "period"),
)

EXPENSES = TableContract(
    name="expenses",
    columns={
        "period": Col("date"),
        "concept": Col("str"),
        "amount": Col("float"),
        "notes": Col("str", required=False),
    },
    primary_key=("period", "concept"),
)

CONTRACTS: dict[str, TableContract] = {
    c.name: c for c in (SALES_LINES, PRODUCTS, CUSTOMERS, PRODUCT_COSTS, EXPENSES)
}


class ContractError(ValueError):
    """Uno o más archivos no cumplen el contrato canónico."""


def validate(df: pd.DataFrame, contract: TableContract, source_file: str) -> None:
    errors: list[str] = []

    missing = [c for c in contract.columns if c not in df.columns]
    if missing:
        errors.append(f"faltan columnas canónicas {missing}")

    for name, spec in contract.columns.items():
        if name not in df.columns:
            continue
        s = df[name]
        if spec.required and s.isna().any():
            n = int(s.isna().sum())
            errors.append(f"'{name}' es obligatoria y tiene {n} valores vacíos o inválidos")
        if spec.allowed is not None:
            bad = sorted(set(s.dropna().astype(str)) - spec.allowed)
            if bad:
                errors.append(f"'{name}' tiene valores no permitidos {bad[:5]}")

    pk = list(contract.primary_key)
    if not missing and df.duplicated(subset=pk).any():
        dups = df[df.duplicated(subset=pk, keep=False)][pk].head(3).to_dict("records")
        errors.append(f"clave {pk} duplicada, ejemplos: {dups}")

    if errors:
        raise ContractError(
            f"[{contract.name}] {source_file} no cumple el contrato:\n  - " + "\n  - ".join(errors)
        )
