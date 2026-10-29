from __future__ import annotations

from actforge.worldview.models import ActionIntent
from actforge.worldview.snapshot import Snapshot


class ScriptPolicy:
    """Deterministic pick-can sequence (offline demo)."""

    def __init__(self, goal_object_id: str = "can_cola"):
        self.goal_object_id = goal_object_id
        self._i = 0
        self._retry_used = False
        self._base = [
            ActionIntent(
                thought="加载抓罐流程",
                action="load_skill",
                args={"skill_name": "pick-can"},
            ),
            ActionIntent(
                thought="记下目标",
                action="note_write",
                args={"text": f"目标是 {goal_object_id}，不要抓 cup_white"},
            ),
            ActionIntent(
                thought="到目标上方",
                action="move_above",
                args={"object_id": goal_object_id, "z_offset": 0.12},
            ),
            ActionIntent(
                thought="下降接近",
                action="move_down",
                args={"delta_z": 0.16},
            ),
            ActionIntent(thought="闭合夹爪", action="close_gripper", args={}),
            ActionIntent(thought="抬起", action="lift", args={"delta_z": 0.12}),
            ActionIntent(thought="回到初始位姿", action="return_home", args={}),
            ActionIntent(thought="完成", action="done", args={"reason": "can lifted"}),
        ]

    def decide(self, snap: Snapshot) -> ActionIntent:
        last = snap.last_result
        if (
            last
            and last.get("action") == "close_gripper"
            and not last.get("ok")
            and last.get("message") == "grasp_miss"
            and not self._retry_used
        ):
            self._retry_used = True
            self._i = 0
            self._base = [
                ActionIntent(
                    thought="抓空，加载重试技能",
                    action="load_skill",
                    args={"skill_name": "grasp-retry"},
                ),
                ActionIntent(
                    thought="重新对准",
                    action="move_above",
                    args={"object_id": self.goal_object_id, "z_offset": 0.12},
                ),
                ActionIntent(
                    thought="再下降",
                    action="move_down",
                    args={"delta_z": 0.16},
                ),
                ActionIntent(thought="再闭合", action="close_gripper", args={}),
                ActionIntent(thought="抬起", action="lift", args={"delta_z": 0.12}),
                ActionIntent(thought="回到初始位姿", action="return_home", args={}),
                ActionIntent(thought="完成", action="done", args={"reason": "retry lift"}),
            ]

        if self._i >= len(self._base):
            return ActionIntent(thought="序列结束", action="done", args={"reason": "script_end"})
        intent = self._base[self._i]
        self._i += 1
        return intent


def _wipe_one(coupling_id: str, rag_home: dict) -> list[ActionIntent]:
    return [
        ActionIntent(
            thought="到抹布上方",
            action="move_above",
            args={"object_id": "rag", "z_offset": 0.10},
        ),
        ActionIntent(thought="下降抓抹布", action="move_down", args={"delta_z": 0.12}),
        ActionIntent(thought="抓住抹布", action="close_gripper", args={}),
        ActionIntent(thought="抬起抹布", action="lift", args={"delta_z": 0.10}),
        ActionIntent(
            thought=f"移到{coupling_id}上方",
            action="move_above",
            args={"object_id": coupling_id, "z_offset": 0.08},
        ),
        ActionIntent(thought="擦拭内壁", action="wipe_inner", args={}),
        ActionIntent(thought="移到抹布原位上方", action="move_to", args=dict(rag_home)),
        ActionIntent(thought="把抹布放回原位", action="place_home", args={}),
        ActionIntent(thought="擦拭返回", action="wipe_return", args={}),
    ]


def _measure_one(coupling_id: str, ruler_home: dict) -> list[ActionIntent]:
    return [
        ActionIntent(
            thought="到量尺上方",
            action="move_above",
            args={"object_id": "ruler", "z_offset": 0.10},
        ),
        ActionIntent(thought="下降抓量尺", action="move_down", args={"delta_z": 0.12}),
        ActionIntent(thought="抓住量尺", action="close_gripper", args={}),
        ActionIntent(thought="抬起量尺", action="lift", args={"delta_z": 0.10}),
        ActionIntent(
            thought=f"移到{coupling_id}上方准备测量",
            action="move_above",
            args={"object_id": coupling_id, "z_offset": 0.08},
        ),
        ActionIntent(thought="仪器测量中径", action="measure_inner", args={}),
        ActionIntent(thought="移到量尺原位上方", action="move_to", args=dict(ruler_home)),
        ActionIntent(thought="把量尺放回原位", action="place_home", args={}),
        ActionIntent(thought="上报仪器测量", action="report_measurement", args={}),
        ActionIntent(thought="规则判定", action="rule_judge", args={}),
        ActionIntent(thought="记录归档", action="archive_record", args={}),
    ]


def _inspect_workpiece(
    workpiece: str,
    coupling_id: str,
    rag_home: dict,
    ruler_home: dict,
) -> list[ActionIntent]:
    """单件：准入 → 擦拭返回 → 清理复核 → 测量判定归档 → 回初始位。"""
    return [
        ActionIntent(
            thought=f"接箍{workpiece}任务准入",
            action="task_admit",
            args={"workpiece": workpiece, "object_id": coupling_id},
        ),
        *_wipe_one(coupling_id, rag_home),
        ActionIntent(
            thought=f"接箍{workpiece}清理复核",
            action="cleaning_review",
            args={"result": "clean"},
        ),
        *_measure_one(coupling_id, ruler_home),
        ActionIntent(
            thought=f"接箍{workpiece}完成后回到初始位",
            action="return_home",
            args={},
        ),
    ]


class CouplingScriptPolicy:
    """两件接箍各自擦测一遍：A 合格(Δd=+0.020)，B 不合格(Δd=+0.080)仍归档。"""

    # Match configs/scene_coupling_v1.yaml homes
    RAG_HOME = {"x": 0.30, "y": 0.10, "z": 0.12, "yaw": 0.0}
    RULER_HOME = {"x": 0.30, "y": -0.12, "z": 0.12, "yaw": 0.2}

    def __init__(self) -> None:
        self._i = 0
        self._base = [
            ActionIntent(
                thought="加载接箍中径擦测流程",
                action="load_skill",
                args={"skill_name": "coupling-clean-measure"},
            ),
            ActionIntent(
                thought="记下流程要点",
                action="note_write",
                args={
                    "text": (
                        "接箍A/B分别：准入→擦拭返回→清理复核→测量→判定→归档→回初始位；"
                        "不合格也归档"
                    )
                },
            ),
            *_inspect_workpiece("A", "coupling_A", self.RAG_HOME, self.RULER_HOME),
            *_inspect_workpiece("B", "coupling_B", self.RAG_HOME, self.RULER_HOME),
            ActionIntent(
                thought="两件接箍擦测均已归档",
                action="done",
                args={"reason": "A qualified, B unqualified, both archived"},
            ),
        ]

    def decide(self, snap: Snapshot) -> ActionIntent:
        if self._i >= len(self._base):
            return ActionIntent(thought="序列结束", action="done", args={"reason": "script_end"})
        intent = self._base[self._i]
        self._i += 1
        return intent


def build_script_policy(task_id: str, goal_object_id: str = "can_cola"):
    if task_id == "coupling_clean":
        return CouplingScriptPolicy()
    return ScriptPolicy(goal_object_id=goal_object_id)
