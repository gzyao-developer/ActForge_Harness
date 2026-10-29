"""Next-step hints for coupling inspection (steers LLM toward the A/B pipeline)."""

from __future__ import annotations

from typing import Any

from actforge.worldview.models import WorldState


def _hint(action: str, args: dict[str, Any], why: str) -> dict[str, Any]:
    return {"recommended_action": action, "recommended_args": args, "why": why}


def home_approach(world: WorldState, oid: str) -> dict[str, float] | None:
    home = (world.object_homes or {}).get(oid)
    if home is None:
        return None
    return {
        "x": home.x,
        "y": home.y,
        "z": round(home.z + 0.10, 3),
        "yaw": home.yaw,
    }


def inspection_progress(world: WorldState) -> dict[str, Any]:
    """Compact progress + one recommended next action for the decision model."""
    flags = world.task_flags or {}
    cfg = world.coupling_cfg or {}
    expected = list((cfg.get("workpieces") or {}).keys()) or ["A", "B"]
    archived = list(flags.get("archived_workpieces") or [])
    wp = flags.get("current_workpiece")
    cid = flags.get("current_coupling_id")
    holding = world.robot.holding
    status = flags.get("cleaning_status")

    base = {
        "expected_workpieces": expected,
        "archived_workpieces": archived,
        "current_workpiece": wp,
        "current_coupling_id": cid,
        "measure_allowed": bool(flags.get("measure_allowed")),
        "coupling_wiped": bool(flags.get("coupling_wiped")),
        "coupling_measured": bool(flags.get("coupling_measured")),
        "quality_result": flags.get("quality_result"),
    }

    if expected and all(x in archived for x in expected):
        if not flags.get("returned_home"):
            return {**base, "phase": "return_home", **_hint("return_home", {}, "全部归档后回到初始位")}
        return {
            **base,
            "phase": "finish",
            **_hint("done", {"reason": "all archived"}, "A/B 均已归档，输出 done"),
        }

    next_wp = next((x for x in expected if x not in archived), None)
    if next_wp is None:
        return {**base, "phase": "finish", **_hint("done", {"reason": "complete"}, "流程完成")}

    wp_cfg = (cfg.get("workpieces") or {}).get(next_wp) or {}
    target_oid = str(wp_cfg.get("object_id") or f"coupling_{next_wp}")

    # Finished current piece → home, then admit next
    if wp and wp in archived:
        if not flags.get("returned_home"):
            return {**base, "phase": "return_home", **_hint("return_home", {}, "本件已归档，回到初始位")}
        return {
            **base,
            "phase": "admit",
            **_hint(
                "task_admit",
                {"workpiece": next_wp, "object_id": target_oid},
                f"开始接箍{next_wp}",
            ),
        }

    # Not yet on the workpiece we need
    if wp != next_wp or not cid:
        return {
            **base,
            "phase": "admit",
            **_hint(
                "task_admit",
                {"workpiece": next_wp, "object_id": target_oid},
                f"任务准入接箍{next_wp}",
            ),
        }

    # --- pipeline for current workpiece ---
    if not flags.get("coupling_wiped"):
        if holding != "rag":
            return {
                **base,
                "phase": "wipe",
                **_hint(
                    "move_above",
                    {"object_id": "rag", "z_offset": 0.10},
                    "抓抹布后擦当前接箍：move_down(delta_z=0.12)→close_gripper→lift→"
                    f"move_above({cid})→wipe_inner→放回抹布",
                ),
            }
        return {
            **base,
            "phase": "wipe",
            **_hint(
                "move_above",
                {"object_id": cid, "z_offset": 0.08},
                f"移到 {cid} 上方 wipe_inner，再 move_to 抹布原位 place_home",
            ),
        }

    if status not in ("pending_review", "clean", "debris"):
        if holding == "rag":
            mv = home_approach(world, "rag") or {}
            return {
                **base,
                "phase": "put_rag",
                **_hint("move_to", mv, "放回抹布后执行 wipe_return"),
            }
        return {
            **base,
            "phase": "wipe_return",
            **_hint("wipe_return", {}, "擦拭返回，等待清理复核"),
        }

    if status == "pending_review" or (
        status != "clean" and not flags.get("measure_allowed")
    ):
        return {
            **base,
            "phase": "review",
            **_hint(
                "cleaning_review",
                {"result": "clean"},
                "清理复核：人工确认已洁净，允许测量",
            ),
        }

    if not flags.get("coupling_measured"):
        if holding != "ruler":
            return {
                **base,
                "phase": "measure",
                **_hint(
                    "move_above",
                    {"object_id": "ruler", "z_offset": 0.10},
                    "抓测量尺后测量当前接箍：move_down(0.12)→close→lift→"
                    f"move_above({cid})→measure_inner→放回量尺",
                ),
            }
        return {
            **base,
            "phase": "measure",
            **_hint(
                "move_above",
                {"object_id": cid, "z_offset": 0.08},
                f"移到 {cid} 上方 measure_inner，再放回量尺",
            ),
        }

    if not flags.get("measurement_reported"):
        if holding == "ruler":
            mv = home_approach(world, "ruler") or {}
            return {
                **base,
                "phase": "put_ruler",
                **_hint("move_to", mv, "放回量尺后 report_measurement"),
            }
        return {
            **base,
            "phase": "report",
            **_hint("report_measurement", {}, "上报仪器测量（Δd）"),
        }

    if not flags.get("quality_result"):
        return {
            **base,
            "phase": "judge",
            **_hint("rule_judge", {}, "规则判定：合格或不合格"),
        }

    if wp not in archived:
        return {
            **base,
            "phase": "archive",
            **_hint("archive_record", {}, "记录归档（不合格也必须归档）"),
        }

    return {
        **base,
        "phase": "return_home",
        **_hint("return_home", {}, "回到初始位"),
    }
