"""Corre el proyecto dbt (genérico) contra el warehouse del cliente."""

from __future__ import annotations

import os
import shutil
import subprocess

from sawy.config import ROOT, ClientConfig

DBT_DIR = ROOT / "dbt"


def run(cfg: ClientConfig) -> None:
    dbt = shutil.which("dbt")
    if not dbt:
        raise RuntimeError("No se encontró 'dbt'. Instalá las dependencias: pip install -r requirements.txt")
    env = {**os.environ, "SAWY_DB_PATH": str(cfg.db_path), "DBT_SEND_ANONYMOUS_USAGE_STATS": "false"}
    # `dbt build` = modelos + tests en orden de dependencias. Si un test de
    # datos falla, no se construye nada de lo que depende de él.
    result = subprocess.run(
        [dbt, "build", "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR)],
        env=env,
        cwd=DBT_DIR,
    )
    if result.returncode != 0:
        raise RuntimeError("dbt build falló: revisá los tests de datos que aparecen arriba.")
