"""Runtime assists for coupling LLM flow: anti-loop + auto wipe_return."""

from __future__ import annotations

from collections import deque
from typing import Any

from actforge.inspection.guide import inspection_progress
from actforge.worldview.models import ActionIntent, ActResult, WorldState


def _fp(intent: ActionIntent) -> str:
    args = intent.args or {}
    keys = ("object_id", "workpiece", "result", "delta_z", "x", "y", "z", "supplementary")
    bits = [intent.action]
    for k in keys:
        if k in args and args[k] is not None:
            bits.append(f"{k}={args[k]}")
    return "|".join(bits)


def _needs_wipe_return(world: WorldState) -> bool:
    flags = world.task_flags or {}
    if not flags.get("coupling_wiped"):
        return False
    if flags.get("cleaning_status") in ("pending_review", "clean", "debris"):
        return False
    return world.robot.holding is None


def _needs_put_rag(world: WorldState) -> bool:
    flags = world.task_flags or {}
    return bool(
        flags.get("coupling_wiped")
        and world.robot.holding == "rag"
        and flags.get("cleaning_status") not in ("pending_review", "clean", "debris")
    )


class CouplingFlowAssist:
    """Steer / patch LLM decisions for the A/B inspection pipeline."""

    def __init__(self, *, max_same: int = 2) -> None:
        self.max_same = max_same
        self._recent_fps: deque[str] = deque(maxlen=8)
        self._enabled = False

    def bind_world(self, world: WorldState) -> None:
        self._enabled = bool((world.coupling_cfg or {}).get("workpieces"))

    def override_decide(self, intent: ActionIntent, world: WorldState) -> ActionIntent:
        if not self._enabled:
            return intent

        # 1) Must put rag back before wipe_return / next phase
        if _needs_put_rag(world):
            if intent.action not in ("move_to", "place_home", "open_gripper"):
                from actforge.inspection.guide import home_approach

                mv = home_approach(world, "rag") or {"x": 0.30, "y": 0.10, "z": 0.12}
                return ActionIntent(
                    thought="[flow-assist] 擦完后先放回抹布",
                    action="move_to",
                    args=dict(mv),
                )

        # 2) Empty hand after wipe → must wipe_return before ruler/measure/review
        if _needs_wipe_return(world):
            skip_ok = intent.action in ("wipe_return", "note_write", "memory_search")
            if not skip_ok:
                return ActionIntent(
                    thought="[flow-assist] 抹布已放回，先擦拭返回",
                    action="wipe_return",
                    args={},
                )

        # 3) Break loops: identical fingerprint OR same action name with churning args
        #    (LLM often spam move_above with slightly different object_id/z_offset).
        fp = _fp(intent)
        same_fp = 0
        for prev in reversed(self._recent_fps):
            if prev == fp:
                same_fp += 1
            else:
                break
        same_action = 0
        for prev in reversed(self._recent_fps):
            if prev.split("|", 1)[0] == intent.action:
                same_action += 1
            else:
                break
        stuck = same_fp >= self.max_same or same_action >= max(self.max_same + 1, 3)
        if stuck:
            prog = inspection_progress(world)
            rec_a = prog.get("recommended_action")
            rec_args = dict(prog.get("recommended_args") or {})
            if rec_a and str(rec_a) != intent.action:
                return ActionIntent(
                    thought=f"[flow-assist] 跳出重复 {intent.action} → {rec_a}",
                    action=str(rec_a),
                    args=rec_args,
                )
            hard = self._hard_next(world)
            if hard is not None and hard.action != intent.action:
                return hard
            # Same action stuck on move_*/lift: force next physical step in phase
            if intent.action in ("move_above", "move_to", "move_down", "lift"):
                forced = self._force_progress(world, intent)
                if forced is not None:
                    return forced

        return intent

    def _force_progress(self, world: WorldState, intent: ActionIntent) -> ActionIntent | None:
        """When LLM orbits with moves, push the phase's decisive action."""
        flags = world.task_flags or {}
        holding = world.robot.holding
        cid = flags.get("current_coupling_id") or "coupling_A"
        if holding == "rag" and not flags.get("coupling_wiped"):
            if intent.action != "wipe_inner":
                return ActionIntent(
                    thought="[flow-assist] 持抹布，直接擦拭",
                    action="wipe_inner",
                    args={},
                )
        if holding == "ruler" and flags.get("measure_allowed") and not flags.get("coupling_measured"):
            if intent.action != "measure_inner":
                # Ensure above coupling first once, else measure
                oid = (intent.args or {}).get("object_id")
                if intent.action == "move_above" and oid == cid:
                    return ActionIntent(
                        thought="[flow-assist] 已对准接箍，执行测量",
                        action="measure_inner",
                        args={},
                    )
                return ActionIntent(
                    thought="[flow-assist] 持量尺，移到接箍上方准备测量",
                    action="move_above",
                    args={"object_id": cid, "z_offset": 0.08},
                )
        if holding is None and flags.get("coupling_wiped") and not flags.get("coupling_measured"):
            if flags.get("cleaning_status") == "pending_review":
                return ActionIntent(
                    thought="[flow-assist]",
                    action="cleaning_review",
                    args={"result": "clean"},
                )
        return None

    def record_executed(self, intent: ActionIntent, act_result: ActResult) -> None:
        if not self._enabled or not act_result.ok:
            return
        self._recent_fps.append(_fp(intent))

    def followups_after(
        self, intent: ActionIntent, act_result: ActResult, world: WorldState
    ) -> list[ActionIntent]:
        """Auto business steps the model often skips."""
        if not self._enabled or not act_result.ok:
            return []
        out: list[ActionIntent] = []
        # After placing rag home post-wipe → wipe_return
        if intent.action == "place_home" and _needs_wipe_return(world):
            out.append(
                ActionIntent(
                    thought="[flow-assist] 自动擦拭返回",
                    action="wipe_return",
                    args={},
                )
            )
        return out

    def _hard_next(self, world: WorldState) -> ActionIntent | None:
        flags = world.task_flags or {}
        if _needs_put_rag(world):
            from actforge.inspection.guide import home_approach

            mv = home_approach(world, "rag") or {}
            return ActionIntent(thought="[flow-assist]", action="move_to", args=dict(mv))
        if _needs_wipe_return(world):
            return ActionIntent(thought="[flow-assist]", action="wipe_return", args={})
        if flags.get("cleaning_status") == "pending_review":
            return ActionIntent(
                thought="[flow-assist]",
                action="cleaning_review",
                args={"result": "clean"},
            )
        if flags.get("measure_allowed") and not flags.get("coupling_measured"):
            if world.robot.holding == "ruler":
                cid = flags.get("current_coupling_id") or "coupling_A"
                return ActionIntent(
                    thought="[flow-assist]",
                    action="move_above",
                    args={"object_id": cid, "z_offset": 0.08},
                )
            if world.robot.holding is None:
                return ActionIntent(
                    thought="[flow-assist]",
                    action="move_above",
                    args={"object_id": "ruler", "z_offset": 0.10},
                )
        if flags.get("coupling_measured") and not flags.get("measurement_reported"):
            if world.robot.holding is None:
                return ActionIntent(
                    thought="[flow-assist]", action="report_measurement", args={}
                )
        if flags.get("measurement_reported") and not flags.get("quality_result"):
            return ActionIntent(thought="[flow-assist]", action="rule_judge", args={})
        if flags.get("quality_result"):
            archived = flags.get("archived_workpieces") or []
            if flags.get("current_workpiece") not in archived:
                return ActionIntent(
                    thought="[flow-assist]", action="archive_record", args={}
                )
        return None
