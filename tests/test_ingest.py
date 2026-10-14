"""La ingesta es la frontera con el ERP: tiene que fallar fuerte y claro."""

import shutil
from pathlib import Path

import pytest
import yaml

from sawy.config import CLIENTS_DIR, load_client
from sawy.ingest.contracts import ContractError
from sawy.ingest.loader import load_table, rule_tables


@pytest.fixture
def client_copy(tmp_path: Path):
    """Copia del cliente real para poder romperle los archivos."""
    dst = tmp_path / "clients" / "tostadero_ruta9"
    shutil.copytree(CLIENTS_DIR / "tostadero_ruta9", dst, ignore=shutil.ignore_patterns("*.cache.json"))
    return dst


def test_real_client_loads_and_respects_contracts():
    cfg = load_client("tostadero_ruta9")
    sales = load_table(cfg, "sales_lines")
    assert len(sales) == 3573
    assert set(sales["document_type"]) == {"invoice", "credit_note"}
    nc = sales[sales["document_type"] == "credit_note"]
    assert (nc["net_amount"] < 0).all() and (nc["quantity"] < 0).all()
    assert sales["period"].dt.day.eq(1).all()


def test_credit_notes_with_positive_sign_are_normalized(client_copy):
    raw = client_copy / "raw" / "ventas.csv"
    lines = raw.read_text(encoding="utf-8").splitlines()
    fixed = [lines[0]] + [ln.replace(";-", ";") if ";NC;" in ln else ln for ln in lines[1:]]
    raw.write_text("\n".join(fixed), encoding="utf-8")
    cfg_path = client_copy / "client.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    cfg["sources"]["sales_lines"]["credit_note_sign"] = "positive"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

    sales = load_table(load_client("tostadero_ruta9", client_copy.parent), "sales_lines")
    nc = sales[sales["document_type"] == "credit_note"]
    assert (nc["net_amount"] < 0).all()


def test_wrong_credit_note_sign_config_fails(client_copy):
    cfg_path = client_copy / "client.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    cfg["sources"]["sales_lines"]["credit_note_sign"] = "positive"  # pero vienen negativas
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ContractError, match="signo positivo"):
        load_table(load_client("tostadero_ruta9", client_copy.parent), "sales_lines")


def test_missing_source_column_has_actionable_message(client_copy):
    cfg_path = client_copy / "client.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    cfg["sources"]["sales_lines"]["columns"]["net_amount"] = "total_linea"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ContractError, match="total_linea"):
        load_table(load_client("tostadero_ruta9", client_copy.parent), "sales_lines")


def test_unknown_document_type_fails(client_copy):
    raw = client_copy / "raw" / "ventas.csv"
    text = raw.read_text(encoding="utf-8").replace(";FAC;", ";REM;", 1)
    raw.write_text(text, encoding="utf-8")
    with pytest.raises(ContractError, match="REM"):
        load_table(load_client("tostadero_ruta9", client_copy.parent), "sales_lines")


def test_unparseable_number_fails(client_copy):
    raw = client_copy / "raw" / "costos.csv"
    lines = raw.read_text(encoding="utf-8").splitlines()
    lines[1] = lines[1].replace(";9800;", ";nueve mil;")
    raw.write_text("\n".join(lines), encoding="utf-8")
    with pytest.raises(ContractError, match="unit_cost"):
        load_table(load_client("tostadero_ruta9", client_copy.parent), "product_costs")


def test_rule_tables_follow_config():
    cfg = load_client("tostadero_ruta9")
    rules = rule_tables(cfg)
    assert rules["rule_product_alias"].to_dict("records") == [
        {"source_product_id": "BLEND1K", "product_id": "CAF-BLEND-1K"}
    ]
    assert set(rules["rule_expense_scope"]["concept"]) == {
        "Flete distribucion",
        "Packaging mayorista",
        "Comision plataforma ecommerce",
    }
    assert rules["cfg_allocation_methods"]["is_default"].sum() == 1


def test_config_rejects_expense_pointing_to_unknown_channel(client_copy):
    cfg_path = client_copy / "client.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    cfg["rules"]["expenses"][0]["channels"] = ["Mayoristas"]  # typo
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="canales inexistentes"):
        load_client("tostadero_ruta9", client_copy.parent)
