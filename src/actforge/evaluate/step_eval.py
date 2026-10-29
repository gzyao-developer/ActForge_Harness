"""Deterministic step evaluators for the pick-can pipeline."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Optional

import yaml

from actforge.evaluate.models import EvaluateResult
from actforge.worldview.models import ActionIntent, ActResult, Pose, WorldState


def load_evaluate_config(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "enabled": True,
            "threshold": 0.70,
            "max_retries": 2,
            "on_exhausted": "continue",
            "apply_suggestions": True,
        }
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    data.setdefault("enabled", True)
    data.setdefault("threshold", 0.70)
    data.setdefault("max_retries", 7)
    data.setdefault("on_exhausted", "continue")
    data.setdefault("apply_suggestions", True)
    data.setdefault("rewind_on_retry", True)
    data.setdefault("rewind_pause_sec", 0.35)
    return data


def _xy_dist(a: Pose, b: Pose) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


class StepEvaluator:
    """
    Score each ACT against task geometry / outcome.

    Flow (owned by state machine):
      ACT → EVALUATE → score < threshold → redo current action (with suggestions)
                     → score >= threshold → proceed
    """

    def __init__(self, threshold: float = 0.70, goal_object_id: str = "can_cola"):
        self.threshold = threshold
        self.goal_object_id = goal_object_id

    def evaluate(
        self,
        intent: ActionIntent,
        act_result: ActResult,
        world: WorldState,
        *,
        world_before: Optional[WorldState] = None,
        attempt: int = 1,
    ) -> EvaluateResult:
        action = intent.action
        scorer = {
            "load_skill": self._eval_load_skill,
            "note_write": self._eval_ok_action,
            "memory_search": self._eval_ok_action,
            "memory_write": self._eval_ok_action,
            "list_objects": self._eval_ok_action,
            "get_object_pose": self._eval_ok_action,
            "move_above": self._eval_move_above,
            "move_down": self._eval_move_down,
            "close_gripper": self._eval_close_gripper,
            "open_gripper": self._eval_ok_action,
            "lift": self._eval_lift,
            "place_down": self._eval_ok_action,
            "place_home": self._eval_ok_action,
            "move_to": self._eval_ok_action,
            "return_home": self._eval_ok_action,
            "wipe_inner": self._eval_ok_action,
            "measure_inner": self._eval_ok_action,
            "task_admit": self._eval_ok_action,
            "wipe_return": self._eval_ok_action,
            "cleaning_review": self._eval_ok_action,
            "report_measurement": self._eval_ok_action,
            "rule_judge": self._eval_ok_action,
            "archive_record": self._eval_ok_action,
            "done": self._eval_done,
        }.get(action, self._eval_ok_action)

        result = scorer(intent, act_result, world, world_before)
        result.action = action
        result.threshold = self.threshold
        result.passed = result.score >= self.threshold
        result.attempt = attempt
        if not result.feedback:
            result.feedback = (
                f"评估通过(score={result.score:.2f})"
                if result.passed
                else f"评估未通过(score={result.score:.2f})，建议重做：{result.reason}"
            )
        return result

    def _fail(
        self,
        score: float,
        reason: str,
        metrics: dict | None = None,
        suggestions: dict | None = None,
        feedback: str = "",
    ) -> EvaluateResult:
        return EvaluateResult(
            action="",
            score=max(0.0, min(1.0, score)),
            threshold=self.threshold,
            passed=False,
            reason=reason,
            feedback=feedback,
            metrics=metrics or {},
            suggestions=suggestions or {},
        )

    def _pass(
        self,
        score: float,
        reason: str,
        metrics: dict | None = None,
    ) -> EvaluateResult:
        return EvaluateResult(
            action="",
            score=max(0.0, min(1.0, score)),
            threshold=self.threshold,
            passed=True,
            reason=reason,
            metrics=metrics or {},
        )

    def _eval_ok_action(
        self,
        intent: ActionIntent,
        act: ActResult,
        world: WorldState,
        before: Optional[WorldState],
    ) -> EvaluateResult:
        # Soft success: not a perfect 1.0 so motion steps can still stand out
        if act.ok:
            return self._pass(0.90, "action_ok")
        return self._fail(0.2, act.message or "action_failed")

    def _eval_load_skill(
        self,
        intent: ActionIntent,
        act: ActResult,
        world: WorldState,
        before: Optional[WorldState],
    ) -> EvaluateResult:
        if act.ok:
            return self._pass(0.92, "skill_loaded", {"skill": intent.args.get("skill_name")})
        return self._fail(0.0, act.message or "load_skill_failed")

    def _eval_move_above(
        self,
        intent: ActionIntent,
        act: ActResult,
        world: WorldState,
        before: Optional[WorldState],
    ) -> EvaluateResult:
        oid = intent.args.get("object_id") or self.goal_object_id
        obj = world.objects.get(oid)
        if not act.ok or obj is None:
            return self._fail(0.1, act.message or "move_above_failed")
        ee = world.robot.ee_pose
        dist = _xy_dist(ee, obj.xyz)
        xy_tol = max(world.grasp_xy_tolerance, 0.01)
        # Continuous: exact center → ~1.0; at 1×tol → ~0.9; at 3×tol → ~0.7
        xy_score = max(0.0, 1.0 - 0.1 * (dist / xy_tol))
        # Prefer being clearly above the object top
        height_margin = ee.z - (obj.xyz.z + obj.height / 2)
        if height_margin >= 0.10:
            z_score = 0.98
        elif height_margin >= 0.05:
            z_score = 0.90
        elif height_margin >= 0.0:
            z_score = 0.75
        else:
            z_score = 0.35
        score = round(0.65 * xy_score + 0.35 * z_score, 3)
        metrics = {
            "xy_dist": round(dist, 4),
            "ee_z": ee.z,
            "obj_z": obj.xyz.z,
            "height_margin": round(height_margin, 4),
        }
        if score >= self.threshold:
            return self._pass(score, "aligned_above", metrics)
        return self._fail(
            score,
            "not_aligned_above",
            metrics,
            suggestions={"object_id": oid, "z_offset": 0.12},
            feedback=f"末端未对准上方：xy_dist={dist:.3f}，请重做 move_above",
        )

    def _grasp_target(self, world: WorldState, intent: ActionIntent | None = None):
        """Object to judge approach height against (nearest graspable under EE for tool tasks)."""
        goal = world.objects.get(self.goal_object_id)
        if goal is not None and goal.graspable:
            return goal
        ee = world.robot.ee_pose
        best = None
        best_d = 1e9
        for obj in world.objects.values():
            if not obj.graspable:
                continue
            d = _xy_dist(ee, obj.xyz)
            if d < best_d:
                best_d = d
                best = obj
        if best is not None and best_d <= max(world.grasp_xy_tolerance * 3, 0.12):
            return best
        return goal

    def _eval_move_down(
        self,
        intent: ActionIntent,
        act: ActResult,
        world: WorldState,
        before: Optional[WorldState],
    ) -> EvaluateResult:
        obj = self._grasp_target(world, intent)
        if not act.ok or obj is None:
            return self._fail(0.1, act.message or "move_down_failed")
        ee = world.robot.ee_pose
        z_err = abs(ee.z - obj.xyz.z)
        tol = max(world.grasp_z_tolerance, 0.04)
        lowered = True
        if before is not None:
            lowered = ee.z < before.robot.ee_pose.z - 1e-6

        # Graded height quality (never force 1.0 unless nearly perfect):
        # z_err=0 → 1.00; z_err=tol → 0.82; beyond tol decays further
        if z_err <= tol:
            height_score = 1.0 - 0.18 * (z_err / tol)
        else:
            height_score = max(0.0, 0.82 - 0.4 * ((z_err - tol) / tol))
        if not lowered:
            height_score *= 0.65
        score = round(float(height_score), 3)

        metrics = {
            "z_err": round(z_err, 4),
            "ee_z": ee.z,
            "need_z": obj.xyz.z,
            "tol": tol,
        }

        if score >= self.threshold:
            return self._pass(score, "height_ok", metrics)

        # Rewind-aware suggestion: descend from before.z to object center
        if before is not None:
            start_z = before.robot.ee_pose.z
            floor_z = world.table_z + 0.05
            target_z = max(obj.xyz.z, floor_z)
            need_delta = start_z - target_z
            need_delta = float(max(0.02, min(need_delta, start_z - floor_z)))
        else:
            need_delta = max(0.08, z_err + 0.02)

        return self._fail(
            score,
            "too_high_for_grasp",
            metrics,
            suggestions={"delta_z": round(need_delta, 3)},
            feedback=(
                f"高度质量不足 z_err={z_err:.3f}（容差 {tol:.3f}），"
                f"回退后建议 delta_z≈{need_delta:.3f}"
            ),
        )

    def _eval_close_gripper(
        self,
        intent: ActionIntent,
        act: ActResult,
        world: WorldState,
        before: Optional[WorldState],
    ) -> EvaluateResult:
        holding = world.robot.holding
        ee = world.robot.ee_pose
        goal_obj = world.objects.get(self.goal_object_id)

        def _grade_grasp(oid: str) -> EvaluateResult:
            obj = world.objects[oid]
            dist = _xy_dist(ee, obj.xyz)
            z_err = abs(ee.z - obj.xyz.z)
            xy_tol = max(world.grasp_xy_tolerance, 0.01)
            z_tol = max(world.grasp_z_tolerance, 0.04)
            align = 0.5 * max(0.0, 1.0 - dist / xy_tol) + 0.5 * max(
                0.0, 1.0 - z_err / z_tol
            )
            score = round(0.80 + 0.20 * align, 3)
            return self._pass(
                score,
                "grasped",
                {"holding": oid, "xy_dist": round(dist, 4), "z_err": round(z_err, 4)},
            )

        if holding == self.goal_object_id:
            return _grade_grasp(holding)
        # Coupling A/B (or missing goal id): tools rag/ruler are valid grasps
        coupling_task = bool(world.coupling_cfg.get("workpieces")) or (
            goal_obj is not None and not goal_obj.graspable
        )
        if holding and coupling_task:
            held = world.objects.get(holding)
            if held is not None and held.graspable:
                return _grade_grasp(holding)
        if holding and goal_obj is not None and not goal_obj.graspable:
            return _grade_grasp(holding)
        if holding and holding != self.goal_object_id:
            return self._fail(
                0.15,
                "wrong_object",
                {"holding": holding},
                feedback=f"抓错物体 {holding}，应抓 {self.goal_object_id}",
            )
        return self._fail(
            0.1,
            act.message or "grasp_miss",
            {"holding": holding},
            suggestions={},
            feedback=(
                "抓取失败 grasp_miss：请先 open_gripper（若已闭合），"
                "再 move_above 目标 → move_down(delta_z=0.12) → close_gripper"
            ),
        )

    def _eval_lift(
        self,
        intent: ActionIntent,
        act: ActResult,
        world: WorldState,
        before: Optional[WorldState],
    ) -> EvaluateResult:
        if not act.ok:
            return self._fail(0.1, act.message or "lift_failed")
        holding = world.robot.holding
        if holding is None:
            return self._fail(
                0.2,
                "lift_without_holding",
                {"holding": holding},
                suggestions={"delta_z": 0.12},
                feedback="抬起时未持有物体，评估不通过",
            )
        goal_obj = world.objects.get(self.goal_object_id)
        # Pick-style goals (graspable target): must lift the goal object
        if goal_obj is not None and goal_obj.graspable and holding != self.goal_object_id:
            return self._fail(
                0.2,
                "lift_wrong_object",
                {"holding": holding},
                suggestions={"delta_z": 0.12},
                feedback=f"应抬起 {self.goal_object_id}，当前 holding={holding}",
            )
        obj = world.objects[holding]
        requested = float(intent.args.get("delta_z", 0.12))
        actual_lift = 0.0
        if before is not None and holding in before.objects:
            actual_lift = obj.xyz.z - before.objects[holding].xyz.z
        # Map lift amount: 0 → low; reach requested → ~0.95; overshoot slight → ~0.98
        if actual_lift <= 0.01:
            score = 0.40
        else:
            ratio = min(actual_lift / max(requested, 1e-6), 1.2)
            score = round(0.55 + 0.40 * min(ratio, 1.0) + (0.03 if ratio >= 1.0 else 0.0), 3)
        metrics = {
            "can_z": obj.xyz.z,
            "holding": holding,
            "actual_lift": round(actual_lift, 4),
            "requested": requested,
        }
        if score >= self.threshold:
            return self._pass(score, "lifted", metrics)
        return self._fail(
            score,
            "not_lifted_enough",
            metrics,
            suggestions={"delta_z": max(requested, 0.12)},
            feedback="抬起高度不足，建议增大 delta_z 后重做 lift",
        )

    def _eval_done(
        self,
        intent: ActionIntent,
        act: ActResult,
        world: WorldState,
        before: Optional[WorldState],
    ) -> EvaluateResult:
        flags = world.task_flags or {}
        archived = list(flags.get("archived_workpieces") or [])
        if archived:
            if world.robot.holding is not None:
                return self._fail(
                    0.4,
                    "hand_not_empty",
                    {"holding": world.robot.holding},
                    feedback="接箍任务完成前请 place_home 放回工具并 return_home",
                )
            if not flags.get("returned_home"):
                return self._fail(
                    0.55,
                    "not_returned_home",
                    {"returned_home": False},
                    feedback="请先 return_home 再 done",
                )
            return self._pass(
                0.96,
                "done_coupling",
                {
                    "archived_workpieces": archived,
                    "workpiece_results": flags.get("workpiece_results"),
                    "returned_home": True,
                },
            )
        if flags.get("coupling_wiped") and flags.get("coupling_measured"):
            if world.robot.holding is not None:
                return self._fail(
                    0.4,
                    "hand_not_empty",
                    {"holding": world.robot.holding},
                    feedback="接箍任务完成前请 place_home 放回工具并 return_home",
                )
            if not flags.get("returned_home"):
                return self._fail(
                    0.55,
                    "not_returned_home",
                    {"returned_home": False},
                    feedback="请先 return_home 再 done",
                )
            return self._pass(
                0.96,
                "done_coupling",
                {
                    "inner_diameter_mm": flags.get("inner_diameter_mm"),
                    "coupling_wiped": True,
                    "coupling_measured": True,
                    "returned_home": True,
                },
            )

        holding = world.robot.holding == self.goal_object_id
        obj = world.objects.get(self.goal_object_id)
        high = obj is not None and obj.xyz.z >= world.table_z + 0.08
        returned = bool(flags.get("returned_home"))
        if holding and high and returned:
            return self._pass(0.98, "done_consistent")
        if holding and high and not returned:
            return self._fail(
                0.55,
                "not_returned_home",
                {"holding": world.robot.holding, "can_z": obj.xyz.z if obj else None},
                feedback="抬起后请 return_home 再 done",
            )
        score = 0.3 if holding else 0.1
        return self._fail(
            score,
            "done_premature",
            {"holding": world.robot.holding, "can_z": obj.xyz.z if obj else None},
            feedback="done 时验收条件未满足，将重试 done 或由后续决策纠正",
        )
