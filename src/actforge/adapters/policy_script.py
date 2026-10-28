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


class CouplingScriptPolicy:
    """Deterministic coupling wipe + measure with put-back and return-home."""

    # Home slots match configs/scene_coupling_v1.yaml (object_homes at reset)
    RAG_HOME = {"x": 0.28, "y": 0.05, "z": 0.12, "yaw": 0.0}
    RULER_HOME = {"x": 0.28, "y": -0.12, "z": 0.12, "yaw": 0.2}

    def __init__(self) -> None:
        self._i = 0
        self._base = [
            ActionIntent(
                thought="加载接箍清洁测量流程",
                action="load_skill",
                args={"skill_name": "coupling-clean-measure"},
            ),
            ActionIntent(
                thought="记下任务",
                action="note_write",
                args={"text": "先擦拭再测量；工具用完放回原位，最后回初始位"},
            ),
            # pick rag
            ActionIntent(
                thought="到抹布上方",
                action="move_above",
                args={"object_id": "rag", "z_offset": 0.10},
            ),
            ActionIntent(thought="下降抓抹布", action="move_down", args={"delta_z": 0.12}),
            ActionIntent(thought="抓住抹布", action="close_gripper", args={}),
            ActionIntent(thought="抬起抹布", action="lift", args={"delta_z": 0.10}),
            # wipe
            ActionIntent(
                thought="移到接箍上方",
                action="move_above",
                args={"object_id": "coupling", "z_offset": 0.08},
            ),
            ActionIntent(thought="擦拭内壁", action="wipe_inner", args={}),
            # put rag back home, then next action
            ActionIntent(
                thought="移到抹布原位上方",
                action="move_to",
                args=dict(self.RAG_HOME),
            ),
            ActionIntent(thought="把抹布放回原位", action="place_home", args={}),
            # pick ruler
            ActionIntent(
                thought="到量尺上方",
                action="move_above",
                args={"object_id": "ruler", "z_offset": 0.10},
            ),
            ActionIntent(thought="下降抓量尺", action="move_down", args={"delta_z": 0.12}),
            ActionIntent(thought="抓住量尺", action="close_gripper", args={}),
            ActionIntent(thought="抬起量尺", action="lift", args={"delta_z": 0.10}),
            # measure
            ActionIntent(
                thought="移到接箍上方准备测量",
                action="move_above",
                args={"object_id": "coupling", "z_offset": 0.08},
            ),
            ActionIntent(thought="测量内径", action="measure_inner", args={}),
            # put ruler back home
            ActionIntent(
                thought="移到量尺原位上方",
                action="move_to",
                args=dict(self.RULER_HOME),
            ),
            ActionIntent(thought="把量尺放回原位", action="place_home", args={}),
            # both tasks end at initial EE pose
            ActionIntent(thought="机械臂回到初始位姿", action="return_home", args={}),
            ActionIntent(
                thought="完成清洁与测量",
                action="done",
                args={"reason": "wiped measured and returned home"},
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
