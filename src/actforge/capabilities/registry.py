from typing import Any

from actforge.adapters.sim_mock import MockSim
from actforge.capabilities.act import ActCapability
from actforge.capabilities.memory_caps import (
    MemorySearchCapability,
    MemoryWriteCapability,
    NoteWriteCapability,
)
from actforge.capabilities.sense import SenseCapability
from actforge.capabilities.skill_caps import LoadSkillCapability
from actforge.inspection.coupling_ops import INSPECTION_ACTIONS, InspectionCapability
from actforge.worldview.models import ActResult, WorldState


class CapabilityRegistry:
    def __init__(self) -> None:
        self._caps: dict[str, Any] = {}

    def register(self, cap: Any) -> None:
        self._caps[cap.name] = cap

    def execute(
        self,
        name: str,
        world: WorldState,
        args: dict,
        ctx: dict[str, Any] | None = None,
    ) -> ActResult:
        cap = self._caps.get(name)
        if cap is None:
            return ActResult(ok=False, action=name, message="unknown_action")
        return cap.execute(world, args or {}, ctx=ctx)


def build_default_registry(sim: Any | None = None) -> CapabilityRegistry:
    sim = sim or MockSim()
    reg = CapabilityRegistry()
    for name in ("list_objects", "get_object_pose"):
        reg.register(SenseCapability(sim, name))
    for name in (
        "move_above",
        "move_down",
        "close_gripper",
        "open_gripper",
        "lift",
        "place_down",
        "place_home",
        "move_to",
        "return_home",
        "wipe_inner",
        "measure_inner",
        "done",
    ):
        reg.register(ActCapability(sim, name))
    for name in INSPECTION_ACTIONS:
        reg.register(InspectionCapability(name))
    reg.register(LoadSkillCapability())
    reg.register(NoteWriteCapability())
    reg.register(MemorySearchCapability())
    reg.register(MemoryWriteCapability())
    return reg
