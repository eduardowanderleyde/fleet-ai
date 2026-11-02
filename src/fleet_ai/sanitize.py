"""O que sai do backend de frota ou do LLM numa resposta pública (ticket 15).

As regras ficam aqui, num lugar só: o despachante aplica a recusa e o estado do
robô aos passos (e o planejador LLM vê o mesmo); o adaptador recusa ids fora do
padrão; as visões da interface web usam as mesmas funções. O texto bruto do
backend vai só para os logs.
"""

import re
import unicodedata
from dataclasses import asdict
from typing import Any

from fleet_ai.contract import RobotStatus

# Identificador de robô ou papel vindo do backend ou do modelo.
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,64}")
MAX_ROBOTS = 100
# Códigos de `last_error` do contrato (ADR-0005); outro texto vira NAV_ERROR.
KNOWN_LAST_ERRORS = frozenset({"", "NAV2_REJECTED", "NAV2_ABORTED"})
MAX_FINAL_TEXT = 2000

# Mensagem do Fleet AI para cada recusa do contrato; nunca o texto do backend.
REFUSAL_MESSAGES = {
    "INVALID_REQUEST": "The fleet rejected the request as invalid.",
    "UNKNOWN_ROBOT": "The robot is not known to the fleet.",
    "ROLE_NOT_ALLOWED": "The robot's role does not allow movement.",
    "ALREADY_NAVIGATING": "The robot is already navigating.",
    "CANCEL_FAILED": "The fleet could not cancel the navigation.",
}


def is_identifier(value: object) -> bool:
    return isinstance(value, str) and IDENTIFIER.fullmatch(value) is not None


def safe_last_error(value: str) -> str:
    return value if value in KNOWN_LAST_ERRORS else "NAV_ERROR"


def safe_role(value: str) -> str:
    return value if is_identifier(value) else "UNKNOWN"


def refusal(error_code: str) -> dict[str, str]:
    """Recusa pública: o código do contrato e a mensagem do Fleet AI para ele."""
    if error_code not in REFUSAL_MESSAGES:
        return {"error_code": "REFUSED", "message": "The fleet refused the command."}
    return {"error_code": error_code, "message": REFUSAL_MESSAGES[error_code]}


def robot_status(status: RobotStatus) -> dict[str, Any]:
    """Estado do robô só com campos do contrato; o `robot_id` já foi validado."""
    return {
        **asdict(status),
        "role": safe_role(status.role),
        "last_error": safe_last_error(status.last_error),
    }


def final_text(text: str) -> str:
    """Texto livre (do modelo) sem caracteres de controle e com tamanho limitado.

    Mantém só a quebra de linha; outros controles e formatadores invisíveis (por
    exemplo, inversão de direção do texto) viram espaço.
    """
    cleaned = "".join(
        c if c == "\n" or unicodedata.category(c) not in {"Cc", "Cf"} else " " for c in text
    )
    return cleaned[:MAX_FINAL_TEXT]
