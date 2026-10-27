"""Missões: a instrução, os passos executados e o resultado (SPEC-001)."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

MissionStatus = Literal[
    "running", "completed", "not_understood", "incomplete", "failed", "rejected"
]


@dataclass
class Mission:
    instruction: str
    robot_id: str | None
    planner: str
    mission_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: MissionStatus = "running"
    language: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    final_text: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "status": self.status,
            "instruction": self.instruction,
            "robot_id": self.robot_id,
            "planner": self.planner,
            "language": self.language,
            "steps": self.steps,
            "final_text": self.final_text,
            "created_at": self.created_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }
