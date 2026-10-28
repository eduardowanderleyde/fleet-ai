"""Configuração do adaptador de frota (SPEC-001, "Seleção do adaptador e health").

Tudo aqui é validado na inicialização, sem nenhuma chamada de rede: a
disponibilidade do backend só é verificada pela sondagem de readiness.
"""

from collections.abc import Mapping
from urllib.parse import urlsplit

import httpx2

from fleet_ai.adapters import FleetAdapter, FleetUiAdapter, SimAdapter

_ADAPTERS: dict[str, type[SimAdapter] | type[FleetUiAdapter]] = {
    "sim": SimAdapter,
    "fleet_ui": FleetUiAdapter,
}
DEFAULT_SIM_URL = "http://localhost:8001"


def fleet_adapter_from_env(
    environ: Mapping[str, str], transport: httpx2.AsyncBaseTransport | None = None
) -> FleetAdapter:
    """O adaptador de FLEET_AI_FLEET_ADAPTER (padrão `sim`) para FLEET_AI_FLEET_URL."""
    name = environ.get("FLEET_AI_FLEET_ADAPTER", "sim")
    if name not in _ADAPTERS:
        raise ValueError(
            f"FLEET_AI_FLEET_ADAPTER must be one of: {', '.join(_ADAPTERS)} (got {name!r})"
        )
    url = environ.get("FLEET_AI_FLEET_URL")
    if url is None:
        if name == "fleet_ui":
            raise ValueError("FLEET_AI_FLEET_URL is required when FLEET_AI_FLEET_ADAPTER=fleet_ui")
        url = DEFAULT_SIM_URL
    problem = _url_problem(url)
    if problem is not None:
        # A mensagem descreve o problema sem repetir a URL, que pode ter credenciais.
        raise ValueError(f"FLEET_AI_FLEET_URL is invalid: {problem}")
    return _ADAPTERS[name](url, transport=transport)


def _url_problem(url: str) -> str | None:
    try:
        parts = urlsplit(url)
        port = parts.port  # levanta ValueError se não for um inteiro de 0 a 65535
    except ValueError:
        return "it is malformed or its port is invalid"
    if port == 0:
        return "the port is invalid"
    if parts.scheme not in ("http", "https"):
        return "the scheme must be http or https"
    if parts.username is not None or parts.password is not None:
        return "credentials are not allowed"
    if not parts.hostname:
        return "the host is missing"
    if "?" in url:
        return "a query is not allowed"
    if "#" in url:
        return "a fragment is not allowed"
    if ";" in parts.path:
        return "path parameters are not allowed"
    return None
