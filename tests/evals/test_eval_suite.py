"""Suíte de avaliação de planejadores (SPEC-005, ticket 01).

Seam: o executor da avaliação (`fleet_eval`) em processo, com Fleet AI e SimFleet
em processo; o LLM roteirizado faz o papel de um modelo que acerta, erra ou tenta
burlar as regras.
"""

import asyncio
from typing import Any

import pytest

from fleet_ai.llm import LlmResponse, ScriptedLlm, TextBlock, ToolUseBlock, Usage
from fleet_eval.cases import Case, Expect
from fleet_eval.report import summarize
from fleet_eval.runner import DETERMINISTIC, Contender, run_case, run_suite

pytestmark = pytest.mark.anyio

DOCK = (2.0, 13.5)  # doca de carga no warehouse
BASE = (0.0, 1.0)


def case(instruction: str, expect: Expect, robot_id: str | None = None) -> Case:
    return Case("c1", "direta", instruction, robot_id, expect)


async def test_case_passes_when_mission_reaches_the_expected_place() -> None:
    result = await run_case(
        case(
            "leve o tb1 até a doca de carga",
            Expect(
                status=("completed",),
                robots=("tb1",),
                place="doca de carga",
                tools=("move_robot", "wait_for_arrival"),
            ),
        ),
        DETERMINISTIC,
    )

    assert result.passed, result.failures
    assert result.status == "completed"
    assert result.moved == ("tb1",)


def tool(call_id: str, name: str, **tool_input: Any) -> ToolUseBlock:
    return ToolUseBlock(call_id, name, tool_input)


def wants(*calls: ToolUseBlock, tokens: tuple[int, int] = (0, 0)) -> LlmResponse:
    return LlmResponse((*calls,), "tool_use", Usage(*tokens))


def says(text: str, tokens: tuple[int, int] = (0, 0)) -> LlmResponse:
    return LlmResponse((TextBlock(text),), "end_turn", Usage(*tokens))


def scripted(*responses: LlmResponse) -> Contender:
    return Contender("scripted", llm_for=lambda _case: ScriptedLlm(responses))


def drive(robot: str, x: float, y: float) -> list[LlmResponse]:
    return [
        wants(tool("m", "move_robot", robot_id=robot, x=x, y=y)),
        wants(tool("w", "wait_for_arrival", robot_id=robot)),
        says("Pronto."),
    ]


TO_DOCK = Expect(
    status=("completed",), robots=("tb1",), place="doca de carga", tools=("move_robot",)
)
REFUSAL = Expect(status=("not_understood",), forbidden=("move_robot",), refusal=True)


@pytest.mark.parametrize(
    ("expect", "contender", "failure"),
    [
        (TO_DOCK, scripted(*drive("tb1", *BASE)), "tb1 did not reach doca de carga"),
        (TO_DOCK, scripted(*drive("tb2", *DOCK)), "moved ['tb2'], expected one of ['tb1']"),
        (TO_DOCK, scripted(says("Não sei.")), "missing tools: move_robot"),
        (REFUSAL, scripted(says("Não sei.")), "status completed, expected not_understood"),
        (REFUSAL, scripted(*drive("tb1", *DOCK)), "forbidden tools: move_robot"),
        (REFUSAL, scripted(*drive("tb1", *DOCK)), "robots moved: tb1"),
    ],
    ids=["wrong_place", "wrong_robot", "missing_tool", "wrong_status", "forbidden", "moved"],
)
async def test_case_fails_on_wrong_place_status_or_forbidden_tool(
    expect: Expect, contender: Contender, failure: str
) -> None:
    result = await run_case(case("leve o tb1 até a doca de carga", expect), contender)

    assert not result.passed
    assert failure in result.failures


async def test_case_fails_when_a_robot_outside_the_scope_moved() -> None:
    # A reescrita estrutural do despachante leva o pedido do tb2 para o tb1; o
    # robô fora do escopo nunca se move, e a avaliação confere isso pela frota.
    expect = Expect(status=("completed",), robots=("tb2",), place="doca de carga")
    result = await run_case(
        case("vá até a doca de carga", expect, robot_id="tb1"), scripted(*drive("tb2", *DOCK))
    )

    assert result.moved == ("tb1",)
    assert "moved ['tb1'], expected one of ['tb2']" in result.failures


async def test_each_case_starts_from_the_initial_fleet_state() -> None:
    first = await run_case(case("leve o tb1 até a doca de carga", TO_DOCK), DETERMINISTIC)
    second = await run_case(case("leve o tb1 até a doca de carga", TO_DOCK), DETERMINISTIC)

    assert first.moved == second.moved == ("tb1",)
    assert first.passed and second.passed


async def test_report_counts_invalid_tool_calls_turns_tokens_and_latency() -> None:
    contender = scripted(
        wants(tool("x", "teleport", robot_id="tb1"), tokens=(100, 10)),
        wants(tool("m", "move_robot", robot_id="tb1", x=DOCK[0]), tokens=(120, 12)),
        wants(tool("m", "move_robot", robot_id="tb1", x=DOCK[0], y=DOCK[1]), tokens=(140, 14)),
        wants(tool("w", "wait_for_arrival", robot_id="tb1"), tokens=(160, 16)),
        says("Pronto.", tokens=(180, 18)),
    )
    results = [
        await run_case(case("leve o tb1 até a doca de carga", TO_DOCK), contender),
        await run_case(
            Case("c2", "impossivel", "leve o tb1 até a cozinha", None, REFUSAL), DETERMINISTIC
        ),
    ]
    report = summarize("scripted", results)

    first = results[0]
    assert (first.llm_turns, first.input_tokens, first.output_tokens) == (5, 700, 70)
    assert first.rejected_tool_calls == 2  # ferramenta desconhecida e input sem `y`
    assert first.tools == ("move_robot", "wait_for_arrival")
    assert report.total.cases == 2 and report.total.passed == 2
    assert report.total.refusals_expected == 1 and report.total.refusals_correct == 1
    assert report.total.rejected_tool_calls == 2
    assert report.total.input_tokens == 700 and report.total.cost_usd == 0.0
    assert set(report.by_category) == {"direta", "impossivel"}
    assert report.by_category["direta"].llm_turns == 5
    assert 0 < report.total.p50_seconds <= report.total.p95_seconds
    table = report.markdown()
    assert "| direta | 1 | 1 | 100% |" in table
    assert "| total | 2 | 2 | 100% |" in table


async def test_case_error_is_recorded_and_the_suite_continues() -> None:
    crashing = Contender("broken", llm_for=lambda _case: _raise())
    cases = [
        case("leve o tb1 até a doca de carga", TO_DOCK),
        Case("c2", "direta", "leve o tb1 até a doca de carga", None, TO_DOCK),
    ]
    results = await run_suite(cases, crashing)

    assert [r.status for r in results] == ["error", "error"]
    assert all(r.error == "RuntimeError" for r in results)
    assert "secret" not in repr(results)


def _raise() -> Any:
    raise RuntimeError("setup failed: secret details")


async def test_cancelling_the_suite_propagates_instead_of_becoming_a_case_error() -> None:
    called = asyncio.Event()

    class Hanging:
        async def complete(self, **_: Any) -> LlmResponse:
            called.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    contender = Contender("hanging", llm_for=lambda _case: Hanging())
    task = asyncio.create_task(
        run_suite([case("leve o tb1 até a doca de carga", TO_DOCK)], contender)
    )
    await called.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
