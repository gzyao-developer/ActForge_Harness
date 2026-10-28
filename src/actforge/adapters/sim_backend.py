"""Replaceable simulation backend protocol (Phase 2 ready)."""

from __future__ import annotations

from typing import Any, Protocol

from actforge.worldview.models import ActResult, WorldState


class SimBackend(Protocol):
    """Simulation backends implement reset + apply; MockSim is the Phase 1 backend."""

    def reset(self, scene_cfg: dict[str, Any] | WorldState) -> WorldState:
        """Create or restore a WorldState from scene config / existing state."""
        ...

    def apply(self, action: str, args: dict, world: WorldState) -> ActResult:
        """Mutate world in place and return ActResult."""
        ...
