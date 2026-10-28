from pathlib import Path

from actforge.adapters.policy_script import ScriptPolicy
from actforge.adapters.sim_mock import MockSim
from actforge.capabilities.registry import build_default_registry
from actforge.evaluate.step_eval import StepEvaluator
from actforge.kernel.state_machine import run_task
from actforge.policy_gate.rules import Gate
from actforge.recall.service import RecallService
from actforge.skillbook.catalog import Skillbook
from actforge.util.config import load_scene
from actforge.util.logging_jsonl import EventLog
from actforge.verify.pick_can import PickCanVerifier
from actforge.worldview.models import ActionIntent, ActResult

ROOT = Path(__file__).resolve().parents[1]


def test_move_down_low_score_suggests_delta_from_before():
    world = load_scene(ROOT / "configs" / "scene_desk_v1.yaml")
    sim = MockSim()
    sim.apply("move_above", {"object_id": "can_cola", "z_offset": 0.12}, world)
    before = world.model_copy(deep=True)
    # insufficient descent
    act = sim.apply("move_down", {"delta_z": 0.02}, world)
    ev = StepEvaluator(threshold=0.7, goal_object_id="can_cola")
    result = ev.evaluate(
        ActionIntent(action="move_down", args={"delta_z": 0.02}),
        act,
        world,
        world_before=before,
    )
    assert not result.passed
    assert "delta_z" in result.suggestions
    # suggestion ≈ before.z - object.z (rewind-aware), not a tiny bump
    expected = before.robot.ee_pose.z - world.objects["can_cola"].xyz.z
    assert abs(result.suggestions["delta_z"] - expected) < 0.05


def test_move_down_within_tolerance_is_graded_not_always_one():
    world = load_scene(ROOT / "configs" / "scene_desk_v1.yaml")
    sim = MockSim()
    sim.apply("move_above", {"object_id": "can_cola", "z_offset": 0.12}, world)
    before = world.model_copy(deep=True)
    act = sim.apply("move_down", {"delta_z": 0.16}, world)
    ev = StepEvaluator(threshold=0.70, goal_object_id="can_cola")
    result = ev.evaluate(
        ActionIntent(action="move_down", args={"delta_z": 0.16}),
        act,
        world,
        world_before=before,
    )
    assert result.passed
    # Good but not forced to exactly 1.0 (small residual z_err → graded)
    assert 0.85 <= result.score <= 1.0
    assert result.score < 1.0 or result.metrics.get("z_err", 1) < 1e-6


def test_close_success_passes():
    world = load_scene(ROOT / "configs" / "scene_desk_v1.yaml")
    sim = MockSim()
    sim.apply("move_above", {"object_id": "can_cola", "z_offset": 0.12}, world)
    sim.apply("move_down", {"delta_z": 0.16}, world)
    act = sim.apply("close_gripper", {}, world)
    ev = StepEvaluator(threshold=0.7, goal_object_id="can_cola")
    result = ev.evaluate(ActionIntent(action="close_gripper", args={}), act, world)
    assert result.passed
    assert result.score >= 0.7


def test_state_machine_retries_bad_move_down(tmp_path):
    """Policy emits tiny move_down once; evaluator should retry with larger delta."""

    class TinyThenNormalPolicy:
        def __init__(self):
            self.seq = [
                ActionIntent(action="load_skill", args={"skill_name": "pick-can"}),
                ActionIntent(
                    action="move_above",
                    args={"object_id": "can_cola", "z_offset": 0.12},
                ),
                ActionIntent(action="move_down", args={"delta_z": 0.02}),
                    ActionIntent(action="close_gripper", args={}),
                    ActionIntent(action="lift", args={"delta_z": 0.12}),
                    ActionIntent(action="return_home", args={}),
                    ActionIntent(action="done", args={}),
                ]
            self.i = 0

        def decide(self, snap):
            intent = self.seq[min(self.i, len(self.seq) - 1)]
            self.i += 1
            return intent

    world = load_scene(ROOT / "configs" / "scene_desk_v1.yaml")
    recall_cfg = {
        "task_notes": {"max_items": 5},
        "durable": {"dir": str(tmp_path / "d"), "top_k": 1, "max_write_chars": 100},
        "tool_experience": {"recent_k": 5, "persist_on_act": False},
        "on_task_success": {"write_durable_summary": False},
    }
    event_log = EventLog("eval", tmp_path / "e.jsonl")
    evaluate_cfg = {
        "enabled": True,
        "threshold": 0.70,
        "max_retries": 2,
        "on_exhausted": "continue",
        "apply_suggestions": True,
    }
    outcome = run_task(
        instruction="拿罐",
        world=world,
        policy=TinyThenNormalPolicy(),
        gate=Gate(),
        registry=build_default_registry(MockSim()),
        verifier=PickCanVerifier("can_cola", 0.10, world.table_z),
        limits={"max_steps": 16, "timeout_sec": 60},
        skillbook=Skillbook(ROOT / "skills"),
        recall=RecallService(recall_cfg, event_log=event_log),
        event_log=event_log,
        goal_object_id="can_cola",
        print_step=False,
        require_load_skill=True,
        evaluator=StepEvaluator(0.70, "can_cola"),
        evaluate_cfg=evaluate_cfg,
        sim=MockSim(),
    )
    assert outcome.status == "success"
    text = (tmp_path / "e.jsonl").read_text(encoding="utf-8")
    assert "evaluate.done" in text
    assert "step.retry" in text
    assert '"rewind": true' in text or '"rewind":true' in text


def test_script_with_evaluate_still_succeeds(tmp_path):
    world = load_scene(ROOT / "configs" / "scene_desk_v1.yaml")
    recall_cfg = {
        "task_notes": {"max_items": 5},
        "durable": {"dir": str(tmp_path / "d2"), "top_k": 1, "max_write_chars": 100},
        "tool_experience": {"recent_k": 5, "persist_on_act": False},
        "on_task_success": {"write_durable_summary": False},
    }
    event_log = EventLog("s", tmp_path / "s.jsonl")
    outcome = run_task(
        instruction="把桌上的易拉罐拿起来",
        world=world,
        policy=ScriptPolicy(),
        gate=Gate(),
        registry=build_default_registry(MockSim()),
        verifier=PickCanVerifier("can_cola", 0.10, 0.0),
        limits={"max_steps": 20, "timeout_sec": 60},
        skillbook=Skillbook(ROOT / "skills"),
        recall=RecallService(recall_cfg, event_log=event_log),
        event_log=event_log,
        goal_object_id="can_cola",
        print_step=False,
        require_load_skill=True,
        evaluator=StepEvaluator(0.7, "can_cola"),
        evaluate_cfg={
            "enabled": True,
            "threshold": 0.7,
            "max_retries": 2,
            "on_exhausted": "continue",
            "apply_suggestions": True,
        },
    )
    assert outcome.status == "success"
