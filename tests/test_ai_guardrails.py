"""La IA no puede escribir cifras: solo citar hechos calculados."""

from sawy.ai.guardrails import globalize, render, validate
from sawy.ai.schema import Action, BeliefCheck, Narrative, strict_json_schema
from sawy.insights.models import Fact

FACTS = {
    "kpi.net_result_total": Fact(value=-1_073_112.5, unit="money", label="resultado"),
    "F1.monthly_loss": Fact(value=808_638, unit="money", label="pérdida mensual"),
    "F1.breakeven_discount": Fact(value=0.3317, unit="pct", label="descuento máximo"),
}
IDS = {"F1", "F2", "F3"}
NAMES = {"Blend Casa 1 kg", "GRANOS DEL SUR S.A."}


def narrative(**over):
    base = dict(
        headline="Perdés plata: el resultado fue [[kpi.net_result_total]].",
        summary=["Granos del Sur te cuesta [[F1.monthly_loss]] por mes.", "El Blend Casa 1 kg deja poco."],
        actions=[
            Action(
                title="Renegociar con GRANOS DEL SUR S.A.",
                why="Bajar el descuento a [[F1.breakeven_discount]].",
                finding_ids=["F1"],
            )
        ]
        * 3,
        beliefs=[
            BeliefCheck(
                belief="El online es poquito", verdict="no se confirma", explanation="Es lo que más deja."
            )
        ],
    )
    base.update(over)
    return Narrative(**base)


def test_valid_narrative_passes():
    assert validate(narrative(), FACTS, IDS, NAMES, ["El online es poquito"]) == []


def test_handwritten_digits_are_rejected():
    n = narrative(headline="Perdiste $1.073.112 en el semestre.")
    errors = validate(n, FACTS, IDS, NAMES, ["El online es poquito"])
    assert any("dígitos" in e for e in errors)


def test_digits_inside_allowed_names_are_ok():
    n = narrative(summary=["El Blend Casa 1 kg deja poco.", "Ojo con el mix."])
    assert validate(n, FACTS, IDS, NAMES, ["El online es poquito"]) == []


def test_unknown_placeholder_and_finding_are_rejected():
    bad = Action(title="Hacer algo", why="Ganarías [[F9.inventado]].", finding_ids=["F9"])
    errors = validate(narrative(actions=[bad] * 3), FACTS, IDS, NAMES, ["El online es poquito"])
    assert any("inexistente" in e for e in errors)
    assert any("hallazgos inválidos" in e for e in errors)


def test_action_count_is_enforced():
    one = narrative().actions[:1]
    errors = validate(narrative(actions=one), FACTS, IDS, NAMES, ["El online es poquito"])
    assert any("entre 3 y 5" in e for e in errors)


def test_render_replaces_with_deterministic_values():
    out = render("Resultado [[kpi.net_result_total]], tope [[F1.breakeven_discount]]", FACTS, "kg")
    assert out == "Resultado −$1,1 M, tope 33%"


def test_globalize_scopes_local_placeholders():
    assert globalize("Perdés [[monthly_loss]] y [[kpi.x]]", "F1") == "Perdés [[F1.monthly_loss]] y [[kpi.x]]"


def test_schema_is_openai_strict_compatible():
    schema = strict_json_schema()

    def walk(node):
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
        for v in node.get("properties", {}).values():
            walk(v)
        if isinstance(node.get("items"), dict):
            walk(node["items"])
        for d in node.get("$defs", {}).values():
            walk(d)

    walk(schema)
