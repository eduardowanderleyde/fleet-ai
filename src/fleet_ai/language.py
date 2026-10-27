"""Idioma de uma instrução (português ou inglês), por palavras-marcadoras."""

import re
import unicodedata
from typing import Literal

Language = Literal["pt", "en"]

# Palavras que só aparecem num dos idiomas; artigos e preposições comuns aos dois
# (como "a") ficam de fora (ticket 07).
# Uma string por grupo, de propósito: como literal, o formatador põe uma palavra por
# linha e a lista fica ilegível de revisar.
_PT_WORDS = set(
    "leve levar mova mover mande envie va ate para o os do da de robo robos frota "
    "liste listar quais qual mostre existem sao onde esta estado posicao "
    "pare parar cancele cancelar interrompa interromper aborte navegacao "
    "depois graus virado".split()
)
_EN_WORDS = set(
    "move send take go drive to the robot robots fleet "
    "list which what show me are there where is how doing of position state "
    "stop cancel abort halt then facing degrees you have".split()
)


def normalize(text: str) -> str:
    """Minúsculas, sem acentos, espaços colapsados."""
    stripped = unicodedata.normalize("NFKD", text.lower())
    without_accents = "".join(char for char in stripped if not unicodedata.combining(char))
    return " ".join(without_accents.split())


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text))


def detect_language(instruction: str) -> Language:
    """Português se houver mais marcadores de português; senão, inglês."""
    found = words(normalize(instruction))
    return "pt" if len(found & _PT_WORDS) > len(found & _EN_WORDS) else "en"
