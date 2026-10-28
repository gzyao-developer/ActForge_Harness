from typing import Any

from actforge.worldview.models import ALLOWED_ACTIONS, ActionIntent, GateResult, WorldState


def check(
    intent: ActionIntent,
    world: WorldState,
    skillbook: Any = None,
    max_text_chars: int = 500,
) -> GateResult:
    action = intent.action
    args = intent.args or {}

    # G1
    if action not in ALLOWED_ACTIONS:
        return GateResult(allowed=False, reason=f"unknown_action:{action}")

    # G2 object_id required / exists
    if action in ("get_object_pose", "move_above"):
        oid = args.get("object_id")
        if not oid:
            return GateResult(allowed=False, reason="missing_object_id")
        if oid not in world.objects:
            return GateResult(allowed=False, reason=f"object_not_found:{oid}")

    # G3 close while holding
    if action == "close_gripper" and world.robot.holding is not None:
        return GateResult(allowed=False, reason="already_holding")

    # G4 lift without holding: allow with warning (Verify will not succeed)
    if action == "lift" and world.robot.holding is None:
        return GateResult(allowed=True, reason="warn_lift_without_holding")

    if action in ("place_down", "place_home") and world.robot.holding is None:
        return GateResult(allowed=False, reason="nothing_to_place")

    if action == "wipe_inner" and world.robot.holding != "rag":
        return GateResult(allowed=False, reason="need_holding_rag")

    if action == "measure_inner" and world.robot.holding != "ruler":
        return GateResult(allowed=False, reason="need_holding_ruler")

    if action == "return_home" and world.home_ee is None:
        return GateResult(allowed=False, reason="no_home_ee")

    # G7 load_skill
    if action == "load_skill":
        skill_name = args.get("skill_name") or args.get("name")
        if not skill_name:
            return GateResult(allowed=False, reason="missing_skill_name")

    # G8 note / memory write text
    if action in ("note_write", "memory_write"):
        text = args.get("text", "")
        if not isinstance(text, str) or not text.strip():
            return GateResult(allowed=False, reason="empty_text")
        if action == "memory_write" and len(text) > max_text_chars:
            return GateResult(allowed=False, reason="text_too_long")

    # G6 soft workspace check for moves
    if action == "move_above":
        oid = args.get("object_id")
        obj = world.objects.get(oid) if oid else None
        if obj is not None:
            b = world.table_bounds
            margin = 0.3
            if (
                obj.xyz.x < b["x_min"] - margin
                or obj.xyz.x > b["x_max"] + margin
                or obj.xyz.y < b["y_min"] - margin
                or obj.xyz.y > b["y_max"] + margin
            ):
                return GateResult(allowed=False, reason="out_of_workspace")

    return GateResult(allowed=True, reason="ok")


class Gate:
    def check(
        self,
        intent: ActionIntent,
        world: WorldState,
        skillbook: Any = None,
        **kwargs: Any,
    ) -> GateResult:
        return check(intent, world, skillbook=skillbook, **kwargs)
