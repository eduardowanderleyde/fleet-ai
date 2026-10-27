"""Caminho de um robô até um destino: A* na grade de planejamento e suavização.

O A* é 8-conectado, não corta quinas e desempata de forma fixa, então o mesmo
pedido sempre produz o mesmo caminho. A suavização por linha de visada valida
cada segmento na grade inflada da resolução original (ADR-0005).
"""

import heapq
import math

from simfleet.occupancy import Cell, OccupancyGrid

Point = tuple[float, float]

_STEPS = (
    (1, 0, 1.0),
    (-1, 0, 1.0),
    (0, 1, 1.0),
    (0, -1, 1.0),
    (1, 1, math.sqrt(2)),
    (1, -1, math.sqrt(2)),
    (-1, 1, math.sqrt(2)),
    (-1, -1, math.sqrt(2)),
)


def plan_path(grid: OccupancyGrid, start: Point, goal: Point) -> list[Point] | None:
    """Caminho de `start` até exatamente `goal`, ou None se não houver."""
    start_cell = grid.planning_cell(*start)
    goal_cell = grid.planning_cell(*goal)
    if start_cell is None or goal_cell is None:
        return None
    if not grid.is_free(*goal) or not grid.is_free_for_planning(*goal):
        return None
    cells = _astar(grid, start_cell, goal_cell)
    if cells is None:
        return None
    raw = [start, *(grid.cell_center(cell) for cell in cells[1:-1]), goal]
    return _smooth(grid, raw)


def _astar(grid: OccupancyGrid, start: Cell, goal: Cell) -> list[Cell] | None:
    blocked = grid.planning_blocked
    rows, cols = blocked.shape

    def free(cell: Cell) -> bool:
        # A célula de partida é sempre livre: o robô pode sair de perto de um obstáculo.
        return cell == start or not blocked[cell]

    def heuristic(cell: Cell) -> float:
        dr, dc = abs(cell[0] - goal[0]), abs(cell[1] - goal[1])
        return (dr + dc) + (math.sqrt(2) - 2) * min(dr, dc)

    best = {start: 0.0}
    came_from: dict[Cell, Cell] = {}
    frontier = [(heuristic(start), 0.0, start)]
    while frontier:
        _, cost, cell = heapq.heappop(frontier)
        if cell == goal:
            path = [cell]
            while cell in came_from:
                cell = came_from[cell]
                path.append(cell)
            return path[::-1]
        if cost > best[cell]:
            continue
        for dr, dc, step in _STEPS:
            nxt = (cell[0] + dr, cell[1] + dc)
            if not (0 <= nxt[0] < rows and 0 <= nxt[1] < cols) or not free(nxt):
                continue
            if dr and dc and not (free((cell[0] + dr, cell[1])) and free((cell[0], cell[1] + dc))):
                continue  # não corta quina
            new_cost = cost + step
            if new_cost < best.get(nxt, math.inf):
                best[nxt] = new_cost
                came_from[nxt] = cell
                heapq.heappush(frontier, (new_cost + heuristic(nxt), new_cost, nxt))
    return None


def _smooth(grid: OccupancyGrid, raw: list[Point]) -> list[Point] | None:
    """A partir de cada ponto, segue até o ponto mais adiante ainda visível em linha reta."""
    path = [raw[0]]
    i = 0
    while i < len(raw) - 1:
        if not grid.segment_is_free(raw[i], raw[i + 1]):
            return None
        j = i + 1
        while j + 1 < len(raw) and grid.segment_is_free(raw[i], raw[j + 1]):
            j += 1
        path.append(raw[j])
        i = j
    return path
