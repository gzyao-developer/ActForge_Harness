from typing import Any, Optional

from pydantic import BaseModel, Field


class EvaluateResult(BaseModel):
    """Per-step automatic evaluation feedback."""

    action: str
    score: float = Field(ge=0.0, le=1.0)
    threshold: float = 0.7
    passed: bool = False
    reason: str = ""
    feedback: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)
    # Suggested arg patches for redo (e.g. larger delta_z)
    suggestions: dict[str, Any] = Field(default_factory=dict)
    attempt: int = 1

    def to_snapshot_dict(self) -> dict[str, Any]:
        return self.model_dump()
