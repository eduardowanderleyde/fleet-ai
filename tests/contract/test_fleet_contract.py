"""A mesma suíte, com os dois adaptadores: o resultado normalizado é igual (ADR-0005)."""

import math

import pytest

from fleet_ai.contract import CommandRefused
from tests.contract.conftest import Backend

pytestmark = pytest.mark.anyio


async def test_list_robots(backend: Backend) -> None:
    assert await backend.executor.list_robots() == ["r1", "r2"]


async def test_robot_status_reports_role_state_and_own_pose(backend: Backend) -> None:
    status = await backend.executor.robot_status("r2")

    assert status.robot_id == "r2"
    assert status.role == "FUUT"
    assert status.nav_state == "idle"
    assert status.last_error == ""
    assert (status.pose.x, status.pose.y) == (2.5, 2.5)


async def test_move_until_arrival(backend: Backend) -> None:
    await backend.executor.move_robot("r1", 2.0, 1.5, yaw=1.2)
    final = await backend.executor.wait_for_navigation("r1")

    assert final.nav_state == "idle"
    assert final.last_error == ""
    assert math.hypot(final.pose.x - 2.0, final.pose.y - 1.5) <= 0.05
    assert final.pose.yaw == pytest.approx(1.2)


@pytest.mark.parametrize("robot_id", ["ghost", ""])
async def test_unknown_robot(backend: Backend, robot_id: str) -> None:
    with pytest.raises(CommandRefused) as move:
        await backend.executor.move_robot(robot_id, 1.0, 1.0)
    with pytest.raises(CommandRefused) as status:
        await backend.executor.robot_status(robot_id)

    assert move.value.error_code == "UNKNOWN_ROBOT"
    assert status.value.error_code == "UNKNOWN_ROBOT"


async def test_fixed_robot_cannot_move(backend: Backend) -> None:
    with pytest.raises(CommandRefused) as refused:
        await backend.executor.move_robot("r2", 1.0, 1.0)

    assert refused.value.error_code == "ROLE_NOT_ALLOWED"
    assert (await backend.executor.robot_status("r2")).nav_state == "idle"


async def test_already_navigating(backend: Backend) -> None:
    await backend.executor.move_robot("r1", 2.5, 0.5)

    with pytest.raises(CommandRefused) as refused:
        await backend.executor.move_robot("r1", 0.5, 2.5)

    assert refused.value.error_code == "ALREADY_NAVIGATING"
    final = await backend.executor.wait_for_navigation("r1")
    assert math.hypot(final.pose.x - 2.5, final.pose.y - 0.5) <= 0.05  # destino original


async def test_impossible_destination_fails_with_nav2_rejected(backend: Backend) -> None:
    await backend.executor.move_robot("r1", 10.0, 10.0)  # fora do mapa nos dois backends
    final = await backend.executor.wait_for_navigation("r1")

    assert final.nav_state == "failed"
    assert final.last_error == "NAV2_REJECTED"
    assert (final.pose.x, final.pose.y) == (0.5, 0.5)


async def test_cancel_of_own_destination_followed_by_idle_is_confirmed(backend: Backend) -> None:
    await backend.executor.move_robot("r1", 2.5, 0.5)
    assert (await backend.executor.robot_status("r1")).nav_state == "navigating"

    outcome = await backend.executor.cancel_navigation("r1")

    assert outcome == "confirmed"
    assert (await backend.executor.robot_status("r1")).nav_state == "idle"


async def test_cancel_while_idle_fails(backend: Backend) -> None:
    with pytest.raises(CommandRefused) as refused:
        await backend.executor.cancel_navigation("r1")

    assert refused.value.error_code == "CANCEL_FAILED"


async def test_cancel_of_a_destination_this_executor_did_not_send_is_ambiguous(
    backend: Backend,
) -> None:
    # Outro cliente do mesmo backend (por exemplo, a interface web do Fleet UI) manda o destino.
    await backend.raw.post("/api/go_to_point", params={"robot_id": "r1", "x": 2.5, "y": 0.5})

    assert await backend.executor.cancel_navigation("r1") == "ambiguous"


@pytest.mark.parametrize(
    ("x", "y", "yaw"), [(math.nan, 1.0, 0.0), (1.0, math.inf, 0.0), (1.0, 1.0, -math.inf)]
)
async def test_non_finite_destination_is_an_invalid_request(
    backend: Backend, x: float, y: float, yaw: float
) -> None:
    with pytest.raises(CommandRefused) as refused:
        await backend.executor.move_robot("r1", x, y, yaw)

    assert refused.value.error_code == "INVALID_REQUEST"
    assert (await backend.executor.robot_status("r1")).nav_state == "idle"
