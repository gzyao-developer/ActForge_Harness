import json
from pathlib import Path

from actforge.adapters.policy_script import ScriptPolicy
from actforge.adapters.sim_mock import MockSim
from actforge.capabilities.registry import build_default_registry
from actforge.kernel.state_machine import run_task
from actforge.policy_gate.rules import Gate
from actforge.recall.service import RecallService
from actforge.skillbook.catalog import Skillbook
from actforge.util.config import load_recall_config, load_scene, load_task
from actforge.util.logging_jsonl import EventLog
from actforge.verify.pick_can import PickCanVerifier

ROOT = Path(__file__).resolve().parents[1]


def test_script_pick_can_success(tmp_path):
    world = load_scene(ROOT / "configs" / "scene_desk_v1.yaml")
    task_cfg = load_task(ROOT / "configs" / "task_pick_can.yaml")
    recall_cfg = load_recall_config(ROOT / "configs" / "recall.yaml")
    recall_cfg = dict(recall_cfg)
    recall_cfg["durable"] = dict(recall_cfg.get("durable", {}))
    recall_cfg["durable"]["dir"] = str(tmp_path / "durable")
    recall_cfg["tool_experience"] = dict(recall_cfg.get("tool_experience", {}))
    recall_cfg["tool_experience"]["persist_jsonl"] = str(tmp_path / "lessons.jsonl")

    log_path = tmp_path / "events.jsonl"
    event_log = EventLog("test", log_path)
    skillbook = Skillbook(ROOT / "skills")
    recall = RecallService(recall_cfg, event_log=event_log)
    goal = task_cfg["goal"]["object_id"]

    outcome = run_task(
        instruction="把桌上的易拉罐拿起来",
        world=world,
        policy=ScriptPolicy(goal_object_id=goal),
        gate=Gate(),
        registry=build_default_registry(MockSim()),
        verifier=PickCanVerifier(goal, float(task_cfg["goal"]["min_lift_z"]), world.table_z),
        limits=task_cfg["limits"],
        skillbook=skillbook,
        recall=recall,
        event_log=event_log,
        goal_object_id=goal,
        print_step=False,
        require_load_skill=True,
    )

    assert outcome.status == "success"
    assert world.robot.holding == "can_cola"

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    types = [json.loads(x)["type"] for x in lines]
    assert "skill.loaded" in types
    assert "memory.note_written" in types


def test_max_steps_fails(tmp_path):
    world = load_scene(ROOT / "configs" / "scene_desk_v1.yaml")
    recall_cfg = {
        "task_notes": {"max_items": 5},
        "durable": {"dir": str(tmp_path / "d"), "top_k": 1, "max_write_chars": 100},
        "tool_experience": {"recent_k": 3, "persist_on_act": False},
        "on_task_success": {"write_durable_summary": False},
    }
    event_log = EventLog("t2", tmp_path / "e.jsonl")
    outcome = run_task(
        instruction="拿罐",
        world=world,
        policy=ScriptPolicy(),
        gate=Gate(),
        registry=build_default_registry(MockSim()),
        verifier=PickCanVerifier("can_cola", 0.10, 0.0),
        limits={"max_steps": 3, "timeout_sec": 60},
        skillbook=Skillbook(ROOT / "skills"),
        recall=RecallService(recall_cfg, event_log=event_log),
        event_log=event_log,
        goal_object_id="can_cola",
        print_step=False,
    )
    assert outcome.status == "failed"
    assert outcome.reason == "max_steps"
