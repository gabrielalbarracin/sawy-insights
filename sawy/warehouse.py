"""Acceso al warehouse analítico.

Todo el código Python habla con esta interfaz chica (write_df / query_df), no
con DuckDB directamente. Cambiar de motor (MotherDuck, BigQuery, Postgres)
implica otra implementación de esta clase + otro adaptador de dbt; el resto
no se entera.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import pandas as pd


class Warehouse(Protocol):
    def write_df(
        self, schema: str, table: str, df: pd.DataFrame, column_types: dict[str, str] | None = None
    ) -> None: ...

    def query_df(self, sql: str, params: list[Any] | None = None) -> pd.DataFrame: ...

    def close(self) -> None: ...


class DuckDBWarehouse:
    def __init__(self, path: Path, read_only: bool = False) -> None:
        import duckdb  # import diferido: los tests unitarios no lo necesitan

        path.parent.mkdir(parents=True, exist_ok=True)
        self._con = duckdb.connect(str(path), read_only=read_only)

    def write_df(
        self, schema: str, table: str, df: pd.DataFrame, column_types: dict[str, str] | None = None
    ) -> None:
        """Escribe (reemplaza) una tabla. `column_types` fuerza tipos SQL para
        que una columna opcional vacía no quede con un tipo inferido raro."""
        types = column_types or {}
        cols = ", ".join(
            f'CAST("{c}" AS {types[c]}) AS "{c}"' if c in types else f'"{c}"' for c in df.columns
        )
        self._con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        self._con.register("_incoming", df)
        try:
            self._con.execute(f"CREATE OR REPLACE TABLE {schema}.{table} AS SELECT {cols} FROM _incoming")
        finally:
            self._con.unregister("_incoming")

    def query_df(self, sql: str, params: list[Any] | None = None) -> pd.DataFrame:
        return self._con.execute(sql, params or []).df()

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> DuckDBWarehouse:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
