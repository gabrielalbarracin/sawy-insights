"""Test de punta a punta (necesita duckdb + dbt; corre en Docker / CI).

Valida números "dorados" contra el análisis exploratorio hecho a mano: si
alguien cambia una regla y mueve el resultado, el test lo dice.
"""

import json
import shutil

import pytest

pytest.importorskip("duckdb")
if not shutil.which("dbt"):
    pytest.skip("dbt no instalado", allow_module_level=True)

from sawy.cli import build  # noqa: E402
from sawy.config import load_client  # noqa: E402


@pytest.fixture(scope="module")
def result():
    import os

    os.environ.pop("OPENAI_API_KEY", None)  # sin llamadas a la API en tests
    build("tostadero_ruta9", refresh_ai=False, publish=False)
    cfg = load_client("tostadero_ruta9")
    return json.loads((cfg.output_dir / "insights.json").read_text(encoding="utf-8"))


def test_company_totals(result):
    k = result["report"]["kpis"]
    assert k["revenue_total"]["value"] == pytest.approx(120_500_593.49, abs=1)
    assert k["gross_margin_total"]["value"] == pytest.approx(33_438_378.49, abs=1)
    assert k["net_result_total"]["value"] == pytest.approx(-1_073_112.51, abs=1)
    assert k["months_negative"]["value"] == 5


def test_main_finding_is_the_distributor_and_is_robust(result):
    f1 = result["report"]["findings"][0]
    assert f1["key"] == "loss_making_customer:C0001"
    assert f1["severity"] == "alta"  # pierde con los tres criterios
    assert f1["depends_on_assumption"] is False
    assert f1["facts"]["breakeven_discount"]["value"] == pytest.approx(0.33, abs=0.01)


def test_dashboard_is_generated(result):
    cfg = load_client("tostadero_ruta9")
    html = (cfg.output_dir / "index.html").read_text(encoding="utf-8")
    assert "¿Estás ganando plata?" in html and "[[" not in html
