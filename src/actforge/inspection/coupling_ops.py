"""接箍中径擦测：业务事件与状态（与执行动作解耦）。

事件名对齐表2：任务准入 / 擦拭返回 / 清理复核 / 补充擦拭 /
仪器测量 / 规则判定 / 记录归档。
"""

from __future__ import annotations

import time
from typing import Any

from actforge.worldview.models import ActResult, WorldState

INSPECTION_ACTIONS = [
    "task_admit",
    "wipe_return",
    "cleaning_review",
    "report_measurement",
    "rule_judge",
    "archive_record",
]


def _elapsed_s(world: WorldState) -> int:
    t0 = world.task_flags.get("inspect_t0")
    if t0 is None:
        return 0
    return max(0, int(time.monotonic() - float(t0)))


def _event(
    world: WorldState,
    *,
    event: str,
    feedback: str,
    disposition: str,
    **extra: Any,
) -> dict[str, Any]:
    wp = world.task_flags.get("current_workpiece", "")
    payload = {
        "time_s": _elapsed_s(world),
        "event": event,
        "feedback": feedback,
        "disposition": disposition,
        "workpiece": wp,
        **extra,
    }
    log = list(world.task_flags.get("inspection_log") or [])
    log.append(payload)
    world.task_flags["inspection_log"] = log
    world.task_flags["last_inspection_event"] = payload
    return payload


def _wp_cfg(world: WorldState) -> dict[str, Any]:
    wp = str(world.task_flags.get("current_workpiece") or "")
    wps = world.coupling_cfg.get("workpieces") or {}
    return dict(wps.get(wp) or {})


class InspectionCapability:
    """Logical inspection steps (no physics)."""

    def __init__(self, name: str):
        self.name = name

    def execute(
        self, world: WorldState, args: dict, ctx: dict[str, Any] | None = None
    ) -> ActResult:
        handlers = {
            "task_admit": self._task_admit,
            "wipe_return": self._wipe_return,
            "cleaning_review": self._cleaning_review,
            "report_measurement": self._report_measurement,
            "rule_judge": self._rule_judge,
            "archive_record": self._archive_record,
        }
        fn = handlers.get(self.name)
        if fn is None:
            return ActResult(ok=False, action=self.name, message="unknown_inspection_action")
        return fn(world, args or {})

    def _task_admit(self, world: WorldState, args: dict) -> ActResult:
        wp = str(args.get("workpiece") or args.get("id") or "A")
        if world.task_flags.get("inspect_t0") is None:
            world.task_flags["inspect_t0"] = time.monotonic()
        world.task_flags["current_workpiece"] = wp
        wp_cfg = _wp_cfg(world)
        oid = args.get("object_id") or wp_cfg.get("object_id")
        if not oid:
            oid = f"coupling_{wp}"
        if oid not in world.objects and "coupling" in world.objects:
            oid = "coupling"
        world.task_flags["current_coupling_id"] = oid
        world.task_flags["measure_allowed"] = False
        world.task_flags["coupling_wiped"] = False
        world.task_flags["coupling_measured"] = False
        world.task_flags["returned_home"] = False
        world.task_flags["measurement_reported"] = False
        world.task_flags.pop("cleaning_status", None)
        world.task_flags.pop("delta_d_mm", None)
        world.task_flags.pop("quality_result", None)
        world.task_flags.pop("judge_reason", None)
        name = world.objects[oid].display_name if oid in world.objects else f"接箍{wp}"
        ev = _event(
            world,
            event="任务准入",
            feedback=f"{name}已到位",
            disposition="开始清理",
            coupling_id=oid,
        )
        return ActResult(
            ok=True,
            action="task_admit",
            message=f"admit_{wp}",
            observation={"inspection_event": ev, "coupling_id": oid},
        )

    def _wipe_return(self, world: WorldState, args: dict) -> ActResult:
        supplementary = bool(args.get("supplementary") or args.get("kind") == "supplementary")
        if not world.task_flags.get("coupling_wiped"):
            return ActResult(ok=False, action="wipe_return", message="not_wiped_yet")
        status = world.task_flags.get("cleaning_status")
        # Idempotent only for the same wipe cycle (assist + script both fire).
        if not supplementary and status == "pending_review":
            return ActResult(
                ok=True,
                action="wipe_return",
                message="already_returned",
                observation={},
            )
        if supplementary:
            world.task_flags["measure_allowed"] = True
            world.task_flags["cleaning_status"] = "clean"
            ev = _event(
                world,
                event="补充擦拭",
                feedback="人工确认已洁净",
                disposition="允许测量",
            )
        else:
            world.task_flags["measure_allowed"] = False
            world.task_flags["cleaning_status"] = "pending_review"
            ev = _event(
                world,
                event="擦拭返回",
                feedback="动作完成",
                disposition="待清理复核",
            )
        return ActResult(
            ok=True,
            action="wipe_return",
            message="supplementary" if supplementary else "wipe_returned",
            observation={"inspection_event": ev},
        )

    def _cleaning_review(self, world: WorldState, args: dict) -> ActResult:
        # Prefer workpiece config simulated review when args omit result
        wp_cfg = _wp_cfg(world)
        raw = args.get("result") or args.get("status") or wp_cfg.get("review_result") or "clean"
        result = str(raw).lower()
        if result in ("debris", "dirty", "异物", "有异物"):
            world.task_flags["measure_allowed"] = False
            world.task_flags["cleaning_status"] = "debris"
            ev = _event(
                world,
                event="清理复核",
                feedback="人工确认有异物",
                disposition="暂缓测量",
            )
            msg = "debris_suspend"
        else:
            world.task_flags["measure_allowed"] = True
            world.task_flags["cleaning_status"] = "clean"
            ev = _event(
                world,
                event="清理复核",
                feedback="人工确认已洁净，允许测量",
                disposition="允许测量",
            )
            msg = "clean_allow"
        return ActResult(
            ok=True,
            action="cleaning_review",
            message=msg,
            observation={"inspection_event": ev},
        )

    def _report_measurement(self, world: WorldState, args: dict) -> ActResult:
        if not world.task_flags.get("coupling_measured"):
            return ActResult(ok=False, action="report_measurement", message="not_measured")
        if not world.task_flags.get("measure_allowed"):
            return ActResult(ok=False, action="report_measurement", message="measure_not_allowed")
        delta = world.task_flags.get("delta_d_mm")
        sign = "+" if float(delta or 0) >= 0 else ""
        world.task_flags["measurement_reported"] = True
        ev = _event(
            world,
            event="仪器测量",
            feedback=f"Δd={sign}{float(delta):.3f}",
            disposition="待判定",
            delta_d_mm=delta,
            measured_d_mm=world.task_flags.get("measured_d_mm"),
            nominal_d_mm=world.task_flags.get("nominal_d_mm"),
        )
        return ActResult(
            ok=True,
            action="report_measurement",
            message=f"delta_{delta}",
            observation={"inspection_event": ev},
        )

    def _rule_judge(self, world: WorldState, args: dict) -> ActResult:
        if not world.task_flags.get("coupling_measured"):
            return ActResult(ok=False, action="rule_judge", message="not_measured")
        delta = float(world.task_flags.get("delta_d_mm", 0.0))
        tol = float(
            args.get("tolerance_mm")
            or world.coupling_cfg.get("tolerance_abs_mm")
            or 0.05
        )
        within = abs(delta) <= tol + 1e-9
        if within:
            world.task_flags["quality_result"] = "qualified"
            world.task_flags["judge_reason"] = "deviation_within_limit"
            ev = _event(
                world,
                event="规则判定",
                feedback="偏差在限内",
                disposition="本项合格",
                tolerance_mm=tol,
            )
            msg = "qualified"
        else:
            world.task_flags["quality_result"] = "unqualified"
            world.task_flags["judge_reason"] = "deviation_exceeds_limit"
            ev = _event(
                world,
                event="规则判定",
                feedback="偏差超限",
                disposition="本项不合格",
                tolerance_mm=tol,
            )
            msg = "unqualified"
        return ActResult(
            ok=True,
            action="rule_judge",
            message=msg,
            observation={"inspection_event": ev, "quality_result": msg},
        )

    def _archive_record(self, world: WorldState, args: dict) -> ActResult:
        wp = world.task_flags.get("current_workpiece")
        quality = world.task_flags.get("quality_result")
        if quality is None:
            return ActResult(ok=False, action="archive_record", message="not_judged")
        results = dict(world.task_flags.get("workpiece_results") or {})
        results[str(wp)] = {
            "quality": quality,
            "delta_d_mm": world.task_flags.get("delta_d_mm"),
            "measured_d_mm": world.task_flags.get("measured_d_mm"),
            "judge_reason": world.task_flags.get("judge_reason"),
        }
        world.task_flags["workpiece_results"] = results
        archived = list(world.task_flags.get("archived_workpieces") or [])
        if wp not in archived:
            archived.append(wp)
        world.task_flags["archived_workpieces"] = archived
        ev = _event(
            world,
            event="记录归档",
            feedback=f"工件{wp}证据齐备",
            disposition="任务完成",
            quality=quality,
        )
        return ActResult(
            ok=True,
            action="archive_record",
            message=f"archived_{wp}_{quality}",
            observation={"inspection_event": ev, "workpiece_results": results},
        )
