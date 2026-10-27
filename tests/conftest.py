import os

import pytest


@pytest.fixture(autouse=True)
def without_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Toda a suíte roda sem nenhuma chave de API no ambiente (ADR-0004)."""
    for name in list(os.environ):
        if name.endswith("_API_KEY"):
            monkeypatch.delenv(name)
