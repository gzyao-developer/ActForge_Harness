from typing import Any

from actforge.adapters.sim_mock import MockSim
from actforge.worldview.models import ActResult, WorldState


class SenseCapability:
    def __init__(self, sim: MockSim, name: str):
        self.name = name
        self.sim = sim

    def execute(
        self, world: WorldState, args: dict, ctx: dict[str, Any] | None = None
    ) -> ActResult:
        return self.sim.apply(self.name, args, world)
