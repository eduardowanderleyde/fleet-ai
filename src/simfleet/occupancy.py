"""Grade de ocupação a partir de uma imagem do map_server, e a grade de planejamento.

Convenções portadas de fleet-ui@9ca98bf:backend/mission/gridmap.py (licença MIT,
ver scenarios/warehouse/SOURCE.md): a linha 0 da imagem é o topo (y máximo), a
origem é o canto inferior esquerdo e pixel abaixo de `free_threshold` (cinza
desconhecido incluído) é ocupado.

A inflação difere da do gridmap.py, que media o raio entre centros de pixel e
deixava um robô chegar mais perto que `inflate_m` de um obstáculo. Aqui um pixel
é bloqueado se a menor distância entre o quadrado dele e o de um pixel ocupado
for menor que `inflate_m`: qualquer ponto de um pixel livre fica a pelo menos
`inflate_m` de todo obstáculo.
"""

import math
from pathlib import Path

import numpy as np
import numpy.typing as npt
from PIL import Image

FREE_THRESHOLD = 240

Cell = tuple[int, int]


class OccupancyGrid:
    """Grade inflada na resolução do mapa e grade de planejamento reduzida.

    A grade de planejamento agrupa `factor` x `factor` pixels; uma célula é
    bloqueada se qualquer pixel dela estiver bloqueado na grade inflada
    (redução conservadora, ADR-0005). Pixels que faltam na borda contam como
    bloqueados.
    """

    def __init__(
        self,
        image: Path,
        resolution: float,
        origin: tuple[float, float],
        inflate_m: float,
        factor: int = 1,
    ) -> None:
        pixels = np.asarray(Image.open(image).convert("L"))
        self.resolution = resolution
        self.origin = origin
        self.blocked = _inflate(np.flipud(pixels < FREE_THRESHOLD), inflate_m / resolution)
        self.factor = factor
        self.cell_size = resolution * factor
        self.planning_blocked = _reduce(self.blocked, factor)

    def is_free(self, x: float, y: float) -> bool:
        """Livre na grade inflada da resolução original."""
        row = math.floor((y - self.origin[1]) / self.resolution)
        col = math.floor((x - self.origin[0]) / self.resolution)
        rows, cols = self.blocked.shape
        return 0 <= row < rows and 0 <= col < cols and not self.blocked[row, col]

    def segment_is_free(self, a: tuple[float, float], b: tuple[float, float]) -> bool:
        """Todo o segmento livre na grade inflada original (amostrado a meia resolução)."""
        samples = max(2, math.ceil(math.dist(a, b) / (self.resolution / 2)) + 1)
        xs = np.linspace(a[0], b[0], samples)
        ys = np.linspace(a[1], b[1], samples)
        rows = np.floor((ys - self.origin[1]) / self.resolution).astype(int)
        cols = np.floor((xs - self.origin[0]) / self.resolution).astype(int)
        n_rows, n_cols = self.blocked.shape
        inside = (rows >= 0) & (rows < n_rows) & (cols >= 0) & (cols < n_cols)
        return bool(inside.all()) and not bool(self.blocked[rows, cols].any())

    def planning_cell(self, x: float, y: float) -> Cell | None:
        row = math.floor((y - self.origin[1]) / self.cell_size)
        col = math.floor((x - self.origin[0]) / self.cell_size)
        rows, cols = self.planning_blocked.shape
        return (row, col) if 0 <= row < rows and 0 <= col < cols else None

    def is_free_for_planning(self, x: float, y: float) -> bool:
        """Livre na grade de planejamento reduzida."""
        cell = self.planning_cell(x, y)
        return cell is not None and not self.planning_blocked[cell]

    def cell_center(self, cell: Cell) -> tuple[float, float]:
        return (
            self.origin[0] + (cell[1] + 0.5) * self.cell_size,
            self.origin[1] + (cell[0] + 0.5) * self.cell_size,
        )


def _inflate(occupied: npt.NDArray[np.bool_], radius_px: float) -> npt.NDArray[np.bool_]:
    """Bloqueia todo pixel cujo quadrado fica a menos de `radius_px` de um pixel ocupado."""
    out = occupied.copy()
    rows, cols = occupied.shape
    reach = math.ceil(radius_px) + 1
    for dr in range(-reach, reach + 1):
        for dc in range(-reach, reach + 1):
            # Distância entre os quadrados de dois pixels a (dr, dc) de distância.
            gap = math.hypot(max(abs(dr) - 1, 0), max(abs(dc) - 1, 0))
            if gap >= radius_px:
                continue
            src = occupied[max(0, -dr) : rows - max(0, dr), max(0, -dc) : cols - max(0, dc)]
            out[max(0, dr) : rows - max(0, -dr), max(0, dc) : cols - max(0, -dc)] |= src
    return out


def _reduce(blocked: npt.NDArray[np.bool_], factor: int) -> npt.NDArray[np.bool_]:
    rows, cols = blocked.shape
    padded = np.ones((math.ceil(rows / factor) * factor, math.ceil(cols / factor) * factor), bool)
    padded[:rows, :cols] = blocked
    reduced: npt.NDArray[np.bool_] = padded.reshape(
        padded.shape[0] // factor, factor, padded.shape[1] // factor, factor
    ).any(axis=(1, 3))
    return reduced
