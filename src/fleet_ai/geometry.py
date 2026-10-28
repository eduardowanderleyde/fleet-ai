"""Conversão entre o mundo (metros) e os pixels do mapa desenhado na interface web.

O mundo tem o eixo y para cima e `yaw` anti-horário a partir de +x; o PNG do mapa
e o canvas têm a primeira linha no topo, com o eixo y para baixo (SPEC-003).
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass

# Mapa sintético quando o backend não tem mapa: resolução, margem e lado máximo.
SYNTHETIC_RESOLUTION = 0.05
SYNTHETIC_MARGIN = 5.0
MAX_SIDE = 4096


@dataclass(frozen=True)
class Frame:
    resolution: float  # metros por pixel
    origin_x: float  # canto inferior esquerdo, em metros
    origin_y: float
    width: int  # pixels
    height: int

    def to_pixel(self, x: float, y: float) -> dict[str, float | bool]:
        """Pixel do canvas para um ponto do mundo; `inside` diz se cai no mapa."""
        px = (x - self.origin_x) / self.resolution
        py = self.height - (y - self.origin_y) / self.resolution
        inside = 0 <= px <= self.width and 0 <= py <= self.height
        return {"x": px, "y": py, "inside": inside}


def canvas_heading(yaw: float) -> float:
    """Ângulo de desenho no canvas: o eixo y invertido troca o sentido da rotação."""
    return -yaw


def synthetic_frame(points: Iterable[tuple[float, float]]) -> Frame:
    """Moldura em volta dos pontos, para desenhar uma grade quando não há mapa."""
    xs, ys = zip(*points, strict=True) if points else ((0.0,), (0.0,))
    min_x, max_x = min(xs) - SYNTHETIC_MARGIN, max(xs) + SYNTHETIC_MARGIN
    min_y, max_y = min(ys) - SYNTHETIC_MARGIN, max(ys) + SYNTHETIC_MARGIN
    span = max(max_x - min_x, max_y - min_y)
    resolution = max(SYNTHETIC_RESOLUTION, span / MAX_SIDE)
    return Frame(
        resolution,
        min_x,
        min_y,
        math.ceil((max_x - min_x) / resolution),
        math.ceil((max_y - min_y) / resolution),
    )
