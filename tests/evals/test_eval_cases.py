"""O arquivo de casos, a linha de base e o isolamento do pacote (SPEC-005, ticket 01)."""

import tomllib
from pathlib import Path

import pytest

from fleet_ai.scenario import load_names
from fleet_eval.cases import CATEGORIES, DEFAULT_CASES, load_cases
from fleet_eval.runner import DETERMINISTIC, run_suite

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "evals" / "baseline.toml"


def test_every_case_file_entry_is_well_formed() -> None:
    cases = load_cases(load_names())

    assert 45 <= len(cases) <= 60
    assert {case.category for case in cases} == set(CATEGORIES)
    for case in cases:
        if case.category == "injecao" and case.expect.place is None:
            assert "move_robot" in case.expect.forbidden, case.id
        if case.expect.refusal:
            assert case.expect.place is None and case.expect.point is None, case.id


VALID = """
[[cases]]
id = "a"
category = "direta"
instruction = "leve o tb1 até a base"
expect = { status = ["completed"], robots = ["tb1"], place = "base" }
"""


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (('category = "direta"', 'category = "outra"'), "unknown category"),
        (('place = "base"', 'place = "cozinha"'), "unknown place"),
        (('robots = ["tb1"]', 'robots = ["tb9"]'), "needs robots"),
        (('["completed"]', '["done"]'), "known statuses"),
        (('place = "base"', 'place = "base", tools = ["teleport"]'), "unknown tool"),
        (('place = "base"', 'place = "base", point = [1, 2]'), "exclusive"),
        (('place = "base"', 'place = "base", refusal = true'), "refusal"),
        (('id = "a"', 'id = "a"\nrobot_id = "tb9"'), "robot_id"),
        (('instruction = "leve o tb1 até a base"', 'instruction = " "'), "empty"),
        (('id = "a"', 'id = "a"\nextra = 1'), "fields"),
    ],
)
def test_malformed_case_is_refused(tmp_path: Path, change: tuple[str, str], message: str) -> None:
    path = tmp_path / "cases.toml"
    path.write_text(VALID.replace(*change))

    with pytest.raises(ValueError, match=message):
        load_cases(load_names(), path)


def test_duplicated_case_ids_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "cases.toml"
    path.write_text(VALID + VALID)

    with pytest.raises(ValueError, match="duplicated case ids: a"):
        load_cases(load_names(), path)


def test_fleet_ai_never_imports_fleet_eval() -> None:
    sources = (ROOT / "src" / "fleet_ai").rglob("*.py")
    assert [p.name for p in sources if "fleet_eval" in p.read_text()] == []
    # A imagem instala só o pacote construído, e ele não traz o fleet_eval.
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    packages = project["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    assert "src/fleet_eval" not in packages


@pytest.mark.anyio
async def test_deterministic_baseline_does_not_regress() -> None:
    baseline = tomllib.loads(BASELINE.read_text())["deterministic"]
    results = await run_suite(load_cases(load_names(), DEFAULT_CASES), DETERMINISTIC)

    failed = {r.case.id for r in results if not r.passed}
    assert failed <= set(baseline["known_failures"]), failed - set(baseline["known_failures"])
    assert len(results) == baseline["cases"]
    assert sum(r.passed for r in results) >= baseline["passed"]
