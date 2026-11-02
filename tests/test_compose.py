"""Compose local: só 127.0.0.1, SimFleet interno, sem LLM pago (ticket 12).

Verificação estática, sem Docker; o roteiro real é `scripts/compose-smoke.sh`.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "compose.yaml"
DOCKERFILE = ROOT / "Dockerfile"
DOCKERIGNORE = ROOT / ".dockerignore"
SMOKE = ROOT / "scripts" / "compose-smoke.sh"


def blocks(text: str, indent: int) -> dict[str, str]:
    """Blocos `nome:` num nível de indentação, com as linhas mais indentadas abaixo."""
    found: dict[str, list[str]] = {}
    current: str | None = None
    key = re.compile(rf"^ {{{indent}}}([A-Za-z0-9_-]+):\s*$")
    for line in text.splitlines():
        match = key.match(line)
        if match:
            current = match.group(1)
            found[current] = []
        elif current and (line.startswith(" " * (indent + 1)) or not line.strip()):
            found[current].append(line)
        elif line.strip():
            current = None
    return {name: "\n".join(lines) for name, lines in found.items()}


def services() -> dict[str, str]:
    top = blocks(COMPOSE.read_text(), 0)
    return blocks(top["services"], 2)


def test_compose_runs_exactly_the_two_services() -> None:
    assert set(services()) == {"fleet-ai", "simfleet"}


def test_fleet_ai_is_published_only_on_localhost() -> None:
    text = COMPOSE.read_text()
    published = re.findall(
        r'^\s+-\s+"?([^"\s]+)"?\s*$', blocks(services()["fleet-ai"], 4)["ports"], re.M
    )

    assert published == ["127.0.0.1:${FLEET_AI_PORT:-8000}:8000"]
    assert "0.0.0.0" not in text  # noqa: S104 - confere a ausência do bind público
    assert "network_mode" not in text  # nada de rede do host


def test_simfleet_has_no_published_port_and_stays_internal() -> None:
    simfleet = blocks(services()["simfleet"], 4)
    networks = blocks(blocks(COMPOSE.read_text(), 0)["networks"], 2)

    assert "ports" not in simfleet and "expose" not in simfleet
    assert re.findall(r"-\s+(\S+)", simfleet["networks"]) == ["internal"]
    assert re.search(r"internal:\s*true", networks["internal"])
    assert re.findall(r"-\s+(\S+)", blocks(services()["fleet-ai"], 4)["networks"]) == [
        "internal",
        "edge",
    ]


def test_demo_configuration_needs_no_llm_or_secret() -> None:
    text = COMPOSE.read_text()
    fleet_ai = blocks(services()["fleet-ai"], 4)["environment"]
    simfleet = blocks(services()["simfleet"], 4)["environment"]

    assert re.search(r"SIMFLEET_TIME_SCALE:\s*\"?3\"?\s*$", simfleet, re.M)
    assert re.search(r"FLEET_AI_PLANNER:\s*deterministic\s*$", fleet_ai, re.M)
    assert re.search(r"FLEET_AI_FLEET_ADAPTER:\s*sim\s*$", fleet_ai, re.M)
    assert re.search(r"FLEET_AI_FLEET_URL:\s*http://simfleet:8001\s*$", fleet_ai, re.M)
    assert not re.search(r"KEY|TOKEN|SECRET|PASSWORD|ANTHROPIC|OPENAI", text, re.I)
    assert "env_file" not in text
    assert "FLEET_AI_LLM" not in text


def test_services_are_healthchecked_restarted_limited_and_rotate_logs() -> None:
    for name, path in (("fleet-ai", "/health/live"), ("simfleet", "/health")):
        service = blocks(services()[name], 4)
        assert path in service["healthcheck"], name
        assert re.search(rf"{re.escape(path)}['\"]", service["healthcheck"]), name
        assert re.search(r"restart:\s*unless-stopped", services()[name]), name
        assert re.search(r"mem_limit:\s*\d+m", services()[name]), name
        assert re.search(r"cpus:", services()[name]), name
        assert re.search(r"pids_limit:\s*\d+", services()[name]), name
        assert re.search(r"read_only:\s*true", services()[name]), name
        assert re.search(r"no-new-privileges:true", services()[name]), name
        assert re.search(r"-\s+ALL", service["cap_drop"]), name
        assert re.search(r'max-size:\s*"?10m"?', services()[name]), name
        assert re.search(r'max-file:\s*"?3"?', services()[name]), name
    # O Fleet AI nunca usa a readiness como liveness: não reinicia quando o backend cai.
    assert "/health'" not in blocks(services()["fleet-ai"], 4)["healthcheck"]
    assert re.search(r"simfleet:\s*\n\s+condition:\s*service_healthy", services()["fleet-ai"])
    assert re.search(r"mem_limit:\s*256m", services()["simfleet"])


def test_shutdown_has_time_to_finish_before_the_kill() -> None:
    for name in ("fleet-ai", "simfleet"):
        assert re.search(r"stop_grace_period:\s*20s", services()[name]), name
        assert re.search(r"init:\s*true", services()[name]), name
    stages = re.split(r"^FROM\s+", DOCKERFILE.read_text(), flags=re.M)
    for target in ("fleet-ai", "simfleet"):
        [stage] = [s for s in stages if re.match(rf"\S+\s+AS\s+{target}\s", s, re.I)]
        assert '"--timeout-graceful-shutdown", "10"' in stage, target


def test_two_image_targets_run_as_non_root_and_ship_the_web_assets() -> None:
    dockerfile = DOCKERFILE.read_text()
    targets = re.findall(r"^FROM\s+\S+\s+AS\s+(\S+)", dockerfile, re.M | re.I)

    assert {"fleet-ai", "simfleet"} <= set(targets)
    assert re.search(r"^USER\s+10001", dockerfile, re.M)
    assert "--frozen" in dockerfile and "--no-dev" in dockerfile
    for name in ("fleet-ai", "simfleet"):
        assert re.search(rf"target:\s*{name}\s*$", services()[name], re.M), name
    # A interface é parte do pacote fleet_ai; o roteiro real confere que é servida.
    assert "/static/app.js" in SMOKE.read_text()
    ignored = DOCKERIGNORE.read_text().split()
    assert {".git", ".venv", ".env*", "tests", ".scratch"} <= set(ignored)
    assert "src" not in ignored and "src/fleet_ai/web" not in ignored


def test_smoke_script_is_isolated_from_the_running_demo() -> None:
    script = SMOKE.read_text()

    assert SMOKE.stat().st_mode & 0o111
    assert re.search(r"FLEET_AI_PORT=\S*8010", script)
    assert re.search(r"-p\s+\"?\$\{?PROJECT", script)  # nome de projeto exclusivo
    assert re.search(r"^trap\s+.*\bcleanup\b.*EXIT", script, re.M)
    for forbidden in (
        "system prune",
        "volume prune",
        "image prune",
        "rm -f $(docker",
        "kill $(docker",
    ):
        assert forbidden not in script, forbidden
