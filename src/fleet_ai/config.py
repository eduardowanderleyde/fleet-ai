"""Configuração do adaptador de frota (SPEC-001, "Seleção do adaptador e health").

Tudo aqui é validado na inicialização, sem nenhuma chamada de rede: a
disponibilidade do backend só é verificada pela sondagem de readiness.
"""

import re
from collections.abc import Mapping
from urllib.parse import urlsplit

import httpx2

from fleet_ai.adapters import FleetAdapter, FleetUiAdapter, SimAdapter
from fleet_ai.guards import positive_float, positive_int
from fleet_ai.llm import LlmPort
from fleet_ai.llm_openai import DEFAULT_TIMEOUT_S, OpenAICompatLlm
from fleet_ai.llm_planner import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MAX_TOOL_CALLS_PER_TURN,
    DEFAULT_MAX_TURNS,
    LlmPlanner,
)
from fleet_ai.planning import DeterministicPlanner, Planner
from fleet_ai.scenario import ScenarioNames

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


_LLM_ADAPTERS = ("scripted", "openai_compat")
_MODEL = re.compile(r"[A-Za-z0-9._:/-]{1,128}")


def llm_from_env(
    environ: Mapping[str, str], transport: httpx2.AsyncBaseTransport | None = None
) -> OpenAICompatLlm | None:
    """O LLM de FLEET_AI_LLM_ADAPTER: `scripted` (padrão, injetado nos testes) ou
    `openai_compat` (um modelo local, como o Ollama; ADR-0007).

    Validado na inicialização, sem rede. Nenhuma chave de API é lida: o serviço só
    fala com modelos que não pedem chave.
    """
    adapter = environ.get("FLEET_AI_LLM_ADAPTER", "scripted")
    if adapter not in _LLM_ADAPTERS:
        raise ValueError(
            f"FLEET_AI_LLM_ADAPTER must be one of: {', '.join(_LLM_ADAPTERS)} (got {adapter!r})"
        )
    if adapter == "scripted":
        return None
    url = environ.get("FLEET_AI_LLM_URL")
    if url is None:
        raise ValueError("FLEET_AI_LLM_URL is required when FLEET_AI_LLM_ADAPTER=openai_compat")
    problem = _url_problem(url)
    if problem is not None:
        raise ValueError(f"FLEET_AI_LLM_URL is invalid: {problem}")
    model = environ.get("FLEET_AI_LLM_MODEL")
    if model is None:
        raise ValueError("FLEET_AI_LLM_MODEL is required when FLEET_AI_LLM_ADAPTER=openai_compat")
    if not _MODEL.fullmatch(model):
        raise ValueError("FLEET_AI_LLM_MODEL must be a model name like qwen2.5:3b")
    timeout = positive_float(environ, "FLEET_AI_LLM_TIMEOUT_S", DEFAULT_TIMEOUT_S)
    return OpenAICompatLlm(url, model, timeout=timeout, transport=transport)


def planner_from_env(
    environ: Mapping[str, str], names: ScenarioNames, llm: LlmPort | None
) -> Planner:
    """O planejador de FLEET_AI_PLANNER: `deterministic` (padrão) ou `llm`.

    O planejador `llm` usa o LLM injetado no `create_app` (o roteirizado, nos
    testes) ou o de `llm_from_env`. Qualquer outra configuração falha de forma
    explícita na inicialização.
    """
    name = environ.get("FLEET_AI_PLANNER", "deterministic")
    if name == "deterministic":
        return DeterministicPlanner(names)
    if name != "llm":
        raise ValueError(f"FLEET_AI_PLANNER must be one of: deterministic, llm (got {name!r})")
    if llm is None:
        raise ValueError(
            "FLEET_AI_PLANNER=llm requires FLEET_AI_LLM_ADAPTER=openai_compat "
            "or a scripted LLM injected in create_app"
        )
    return LlmPlanner(
        llm,
        max_turns=positive_int(environ, "FLEET_AI_LLM_MAX_TURNS", DEFAULT_MAX_TURNS),
        max_tool_calls_per_turn=positive_int(
            environ, "FLEET_AI_LLM_MAX_TOOL_CALLS_PER_TURN", DEFAULT_MAX_TOOL_CALLS_PER_TURN
        ),
        max_tokens=positive_int(environ, "FLEET_AI_LLM_MAX_TOKENS", DEFAULT_MAX_TOKENS),
        names=names,
    )
