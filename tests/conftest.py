import os

import pytest


@pytest.fixture(autouse=True)
def without_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Toda a suíte roda sem nenhuma chave de API no ambiente (ADR-0004)."""
    for name in list(os.environ):
        if name.endswith("_API_KEY"):
            monkeypatch.delenv(name)


@pytest.fixture(autouse=True)
def without_scenario_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Variáveis de configuração do shell não podem mudar o comportamento dos testes."""
    monkeypatch.delenv("SIMFLEET_SCENARIO", raising=False)
    monkeypatch.delenv("SIMFLEET_TIME_SCALE", raising=False)
    monkeypatch.delenv("FLEET_AI_SCENARIO", raising=False)
