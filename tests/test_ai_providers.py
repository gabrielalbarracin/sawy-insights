import pytest

from sawy.ai import providers


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ("LLM_PROVIDER", "LLM_MODEL", "GEMINI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)


def test_no_key_means_no_ai():
    assert providers.resolve() is None


def test_gemini_uses_openai_compatible_endpoint(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    cfg = providers.resolve()
    assert cfg.provider.name == "gemini"
    assert "generativelanguage.googleapis.com" in cfg.provider.base_url


def test_explicit_provider_and_model(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_MODEL", "otro-modelo")
    cfg = providers.resolve()
    assert (cfg.provider.name, cfg.api_key, cfg.model) == ("openai", "o", "otro-modelo")


def test_unknown_provider_fails_clearly(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "claudio")
    with pytest.raises(ValueError, match="no existe"):
        providers.resolve()


def test_strip_code_fences():
    assert providers._strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert providers._strip_fences('{"a": 1}') == '{"a": 1}'
