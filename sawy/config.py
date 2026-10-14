"""Configuración de un cliente (client.yaml), validada con Pydantic.

Un error de configuración tiene que fallar temprano y con un mensaje claro,
no tres pasos después como un número raro en el dashboard.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AllocationMethod = Literal["base_units", "net_amount", "deliveries"]

ROOT = Path(__file__).resolve().parent.parent
CLIENTS_DIR = ROOT / "clients"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FileFormat(_Strict):
    sep: str = ","
    decimal: str = "."
    encoding: str = "utf-8"
    date_format: str | None = None
    period_format: str | None = None


class SourceSpec(_Strict):
    file: str
    format: FileFormat = FileFormat()
    columns: dict[str, str]  # canonical -> source
    document_types: dict[str, Literal["invoice", "credit_note"]] | None = None
    credit_note_sign: Literal["negative", "positive"] | None = None
    boolean_values: dict[str, bool] | None = None


class Sources(_Strict):
    sales_lines: SourceSpec
    products: SourceSpec
    customers: SourceSpec
    product_costs: SourceSpec
    expenses: SourceSpec


class ChannelRule(_Strict):
    segment: str
    channel: str
    named_customers: bool = True


class ExpenseRule(_Strict):
    concept: str
    label: str | None = None  # cómo se lo nombra en lenguaje simple ("el flete")
    behavior: Literal["variable", "fixed"]
    channels: list[str] = Field(default_factory=list)
    driver: AllocationMethod | None = None
    sensitive: bool = False

    @model_validator(mode="after")
    def _variable_needs_scope(self) -> ExpenseRule:
        if self.behavior == "variable" and (not self.channels or not self.driver):
            raise ValueError(f"El gasto variable '{self.concept}' necesita 'channels' y 'driver'.")
        return self


class Rules(_Strict):
    product_aliases: dict[str, str] = Field(default_factory=dict)
    base_units_per_unit: dict[str, float] = Field(default_factory=dict)
    channels: list[ChannelRule]
    expenses: list[ExpenseRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def _expense_channels_exist(self) -> Rules:
        known = {c.channel for c in self.channels}
        for e in self.expenses:
            unknown = set(e.channels) - known
            if unknown:
                raise ValueError(f"El gasto '{e.concept}' apunta a canales inexistentes: {sorted(unknown)}")
        return self


class Thresholds(_Strict):
    min_revenue_share_customer: float = 0.02  # clientes con <2% de la venta no se alertan por rentabilidad
    return_rate_alert: float = 0.08  # devoluciones >8% de lo vendido
    min_returned_units: float = 10
    cooling_recent_months: int = 2
    cooling_ratio: float = 0.5  # compra reciente < 50% de lo habitual
    cross_sell_min_penetration: float = 0.25  # al menos 25% de los pares lo compra
    cross_sell_min_non_buyers: int = 3
    max_findings_per_kind: int = 5


class Analysis(_Strict):
    allocation_methods: list[AllocationMethod] = ["base_units", "net_amount", "deliveries"]
    default_allocation_method: AllocationMethod = "base_units"
    thresholds: Thresholds = Thresholds()

    @field_validator("allocation_methods")
    @classmethod
    def _non_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("allocation_methods no puede estar vacío")
        return v

    @model_validator(mode="after")
    def _default_in_methods(self) -> Analysis:
        if self.default_allocation_method not in self.allocation_methods:
            raise ValueError("default_allocation_method debe estar en allocation_methods")
        return self


class ClientInfo(_Strict):
    id: str
    name: str
    owner_name: str | None = None
    currency: str = "ARS"
    base_unit: str = "unidad"
    business_context: str = ""
    owner_beliefs: list[str] = Field(default_factory=list)


class ClientConfig(_Strict):
    client: ClientInfo
    sources: Sources
    rules: Rules
    analysis: Analysis = Analysis()

    # No es parte del YAML: se completa al cargar
    base_dir: Path = Field(default=Path("."), exclude=True)

    @property
    def output_dir(self) -> Path:
        return ROOT / "output" / self.client.id

    @property
    def db_path(self) -> Path:
        return self.output_dir / "warehouse.duckdb"


def load_client(client_id: str, clients_dir: Path = CLIENTS_DIR) -> ClientConfig:
    base = clients_dir / client_id
    path = base / "client.yaml"
    if not path.exists():
        available = sorted(p.name for p in clients_dir.iterdir() if (p / "client.yaml").exists())
        raise FileNotFoundError(f"No existe el cliente '{client_id}'. Disponibles: {available}")
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    cfg = ClientConfig.model_validate(raw)
    cfg.base_dir = base
    return cfg
