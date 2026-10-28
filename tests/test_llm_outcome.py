from pathlib import Path

from actforge.adapters.llm_openai import LLMPolicyError
from actforge.adapters.sim_mock import MockSim
from actforge.capabilities.registry import build_default_registry
from actforge.kernel.state_machine import run_task
from actforge.policy_gate.rules import Gate
from actforge.recall.service import RecallService
from actforge.skillbook.catalog import Skillbook
from actforge.util.config import load_scene
from actforge.util.logging_jsonl import EventLog
from actforge.verify.pick_can import PickCanVerifier
from actforge.worldview.models import ActionIntent
from actforge.worldview.snapshot import Snapshot

ROOT = Path(__file__).resolve().parents[1]


class BoomPolicy:
    def decide(self, snap: Snapshot) -> ActionIntent:
        raise LLMPolicyError("llm_parse_exhausted", "bad json")


class AlwaysBadObjectPolicy:
    """Same gated failure every step → repeated_failure."""

    def decide(self, snap: Snapshot) -> ActionIntent:
        return ActionIntent(action="move_above", args={"object_id": "not_exist"})


def test_llm_parse_exhausted_becomes_outcome(tmp_path):
    world = load_scene(ROOT / "configs" / "scene_desk_v1.yaml")
    recall_cfg = {
        "task_notes": {"max_items": 5},
        "durable": {"dir": str(tmp_path / "d"), "top_k": 1, "max_write_chars": 100},
        "tool_experience": {"recent_k": 3, "persist_on_act": False},
        "on_task_success": {"write_durable_summary": False},
    }
    event_log = EventLog("llmfail", tmp_path / "e.jsonl")
    outcome = run_task(
        instruction="拿罐",
        world=world,
        policy=BoomPolicy(),
        gate=Gate(),
        registry=build_default_registry(MockSim()),
        verifier=PickCanVerifier("can_cola", 0.10, 0.0),
        limits={"max_steps": 5, "timeout_sec": 30},
        skillbook=Skillbook(ROOT / "skills"),
        recall=RecallService(recall_cfg, event_log=event_log),
        event_log=event_log,
        goal_object_id="can_cola",
        print_step=False,
    )
    assert outcome.status == "failed"
    assert outcome.reason == "llm_parse_exhausted"


def test_repeated_failure_ends_task(tmp_path):
    world = load_scene(ROOT / "configs" / "scene_desk_v1.yaml")
    recall_cfg = {
        "task_notes": {"max_items": 5},
        "durable": {"dir": str(tmp_path / "d2"), "top_k": 1, "max_write_chars": 100},
        "tool_experience": {"recent_k": 3, "persist_on_act": False},
        "on_task_success": {"write_durable_summary": False},
    }
    event_log = EventLog("rep", tmp_path / "r.jsonl")
    outcome = run_task(
        instruction="拿罐",
        world=world,
        policy=AlwaysBadObjectPolicy(),
        gate=Gate(),
        registry=build_default_registry(MockSim()),
        verifier=PickCanVerifier("can_cola", 0.10, 0.0),
        limits={"max_steps": 20, "timeout_sec": 60},
        skillbook=Skillbook(ROOT / "skills"),
        recall=RecallService(recall_cfg, event_log=event_log),
        event_log=event_log,
        goal_object_id="can_cola",
        print_step=False,
        max_same_fail=3,
    )
    assert outcome.status == "failed"
    assert outcome.reason == "repeated_failure"
