"""Idioma de uma instrução (português ou inglês), por palavras-marcadoras."""

import re
import unicodedata
from typing import Literal

Language = Literal["pt", "en"]

_PT_WORDS = {"leve", "levar", "mova", "mande", "envie", "va", "ate", "para", "o", "a", "robo"}
_EN_WORDS = {"move", "send", "take", "go", "drive", "to", "the", "robot"}


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
