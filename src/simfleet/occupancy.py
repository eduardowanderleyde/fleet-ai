"""Grade de ocupação a partir de uma imagem do map_server.

Convenções portadas de fleet-ui@9ca98bf:backend/mission/gridmap.py (licença MIT,
ver scenarios/warehouse/SOURCE.md): a linha 0 da imagem é o topo (y máximo), a
origem é o canto inferior esquerdo, pixel abaixo de `free_threshold` (cinza
desconhecido incluído) é ocupado e os obstáculos são inflados num raio circular.
"""

import math
from pathlib import Path

import numpy as np
import numpy.typing as npt
from PIL import Image

FREE_THRESHOLD = 240


class OccupancyGrid:
    def __init__(
        self, image: Path, resolution: float, origin: tuple[float, float], inflate_m: float
    ) -> None:
        pixels = np.asarray(Image.open(image).convert("L"))
        self.resolution = resolution
        self.origin = origin
        self.blocked = _inflate(
            np.flipud(pixels < FREE_THRESHOLD), math.ceil(inflate_m / resolution)
        )

    def is_free(self, x: float, y: float) -> bool:
        row = math.floor((y - self.origin[1]) / self.resolution)
        col = math.floor((x - self.origin[0]) / self.resolution)
        rows, cols = self.blocked.shape
        return 0 <= row < rows and 0 <= col < cols and not self.blocked[row, col]


def _inflate(occupied: npt.NDArray[np.bool_], radius: int) -> npt.NDArray[np.bool_]:
    out = occupied.copy()
    rows, cols = occupied.shape
    for dr in range(-radius, radius + 1):
        for dc in range(-radius, radius + 1):
            if dr * dr + dc * dc > radius * radius:
                continue
            src = occupied[max(0, -dr) : rows - max(0, dr), max(0, -dc) : cols - max(0, dc)]
            out[max(0, dr) : rows - max(0, -dr), max(0, dc) : cols - max(0, -dc)] |= src
    return out
