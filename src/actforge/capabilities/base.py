from typing import Any, Protocol

from actforge.worldview.models import ActResult, WorldState


class Capability(Protocol):
    name: str

    def execute(
        self, world: WorldState, args: dict, ctx: dict[str, Any] | None = None
    ) -> ActResult: ...
