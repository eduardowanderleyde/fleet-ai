"""O roteiro da demo sobe tudo só em 127.0.0.1 (SPEC-003, ticket 01)."""

import re
from pathlib import Path

DEMO = Path(__file__).resolve().parents[2] / "scripts" / "demo.sh"


def test_demo_script_binds_only_to_localhost() -> None:
    script = DEMO.read_text()

    hosts = re.findall(r"--host\s+(\S+)", script)
    assert hosts == ["127.0.0.1", "127.0.0.1"]  # SimFleet e Fleet AI
    assert "0.0.0.0" not in script  # noqa: S104 - confere a ausência do bind público
    assert "FLEET_AI_FLEET_URL=http://127.0.0.1:" in script
    assert "ssh -p <porta-ssh> -L" in script  # imprime o comando do túnel
    assert DEMO.stat().st_mode & 0o111  # executável
