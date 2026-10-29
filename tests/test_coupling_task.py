import json
from pathlib import Path

from actforge.adapters.policy_script import CouplingScriptPolicy, build_script_policy
from actforge.adapters.sim_mock import MockSim
from actforge.capabilities.registry import build_default_registry
from actforge.kernel.state_machine import run_task
from actforge.policy_gate.rules import Gate
from actforge.recall.service import RecallService
from actforge.skillbook.catalog import Skillbook
from actforge.util.config import load_scene
from actforge.util.logging_jsonl import EventLog
from actforge.util.task_router import infer_task_id, load_tasks_catalog, resolve_task_preset
from actforge.verify.coupling_clean import CouplingCleanVerifier

ROOT = Path(__file__).resolve().parents[1]


def test_router_picks_coupling_and_pick_can():
    catalog = load_tasks_catalog(ROOT / "configs" / "tasks.yaml")
    assert infer_task_id("请擦拭接箍并测量内径", catalog) == "coupling_clean"
    assert infer_task_id("把桌上的易拉罐拿起来", catalog) == "pick_can"
    tid, preset = resolve_task_preset("对接箍内壁清洁", ROOT / "configs" / "tasks.yaml")
    assert tid == "coupling_clean"
    assert "coupling" in preset["scene"]


def test_coupling_script_mock_success(tmp_path):
    world = load_scene(ROOT / "configs" / "scene_coupling_v1.yaml")
    assert "coupling_A" in world.objects and "coupling_B" in world.objects
    recall_cfg = {
        "task_notes": {"max_items": 10},
        "durable": {"dir": str(tmp_path / "d"), "top_k": 1, "max_write_chars": 200},
        "tool_experience": {"recent_k": 8, "persist_on_act": False},
        "on_task_success": {"write_durable_summary": False},
    }
    event_log = EventLog("cpl", tmp_path / "e.jsonl")
    outcome = run_task(
        instruction="擦拭接箍并测量内径",
        world=world,
        policy=CouplingScriptPolicy(),
        gate=Gate(),
        registry=build_default_registry(MockSim()),
        verifier=CouplingCleanVerifier(expected_workpieces=["A", "B"]),
        limits={"max_steps": 80, "timeout_sec": 120},
        skillbook=Skillbook(ROOT / "skills"),
        recall=RecallService(recall_cfg, event_log=event_log),
        event_log=event_log,
        goal_object_id="coupling_A",
        print_step=False,
        require_load_skill=True,
        evaluate_cfg={"enabled": False},
    )
    assert outcome.status == "success"
    assert world.task_flags.get("archived_workpieces") == ["A", "B"]
    results = world.task_flags.get("workpiece_results") or {}
    assert results["A"]["quality"] == "qualified"
    assert results["B"]["quality"] == "unqualified"
    assert abs(float(results["A"]["delta_d_mm"]) - 0.020) < 1e-6
    assert abs(float(results["B"]["delta_d_mm"]) - 0.080) < 1e-6
    assert world.robot.holding is None
    assert world.task_flags.get("returned_home") is True

    lines = (tmp_path / "e.jsonl").read_text(encoding="utf-8").strip().splitlines()
    insp = [
        json.loads(x)["payload"]["event"]
        for x in lines
        if json.loads(x).get("type") == "inspection.event"
    ]
    # 每件：准入→擦拭返回→清理复核→仪器测量→规则判定→记录归档（无补充擦拭）
    assert insp.count("任务准入") == 2
    assert insp.count("擦拭返回") == 2
    assert insp.count("清理复核") == 2
    assert insp.count("仪器测量") == 2
    assert insp.count("规则判定") == 2
    assert insp.count("记录归档") == 2
    assert "补充擦拭" not in insp

    reviews = [
        json.loads(x)["payload"]
        for x in lines
        if json.loads(x).get("type") == "inspection.event"
        and json.loads(x)["payload"].get("event") == "清理复核"
    ]
    assert all("允许测量" in (r.get("disposition") or "") for r in reviews)
    assert all("人工确认已洁净" in (r.get("feedback") or "") for r in reviews)
    assert all("模拟" not in (r.get("feedback") or "") for r in reviews)


def test_build_script_policy_switch():
    assert isinstance(build_script_policy("coupling_clean"), CouplingScriptPolicy)
