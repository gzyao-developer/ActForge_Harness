from pathlib import Path

from actforge.recall.service import RecallService
from actforge.worldview.models import ActResult

ROOT = Path(__file__).resolve().parents[1]


def _cfg(tmp_path: Path) -> dict:
    return {
        "task_notes": {"max_items": 20},
        "durable": {
            "dir": str(tmp_path / "durable"),
            "auto_retrieve_each_step": True,
            "top_k": 3,
            "max_write_chars": 500,
        },
        "tool_experience": {
            "recent_k": 5,
            "persist_jsonl": str(tmp_path / "lessons.jsonl"),
            "persist_on_act": True,
        },
        "on_task_success": {"write_durable_summary": False},
    }


def test_task_notes_reset_between_tasks(tmp_path):
    recall = RecallService(_cfg(tmp_path))
    recall.on_task_start("a", "can_cola")
    recall.note_write("hello")
    assert recall.build_recall_snapshot()["task_notes"] == ["hello"]
    recall.on_task_start("b", "can_cola")
    assert recall.build_recall_snapshot()["task_notes"] == []


def test_durable_search(tmp_path):
    recall = RecallService(_cfg(tmp_path))
    recall.on_task_start("拿易拉罐", "can_cola")
    w = recall.memory_write("易拉罐抓取需要 3cm xy 容差", tags=["grasp"])
    assert w.ok
    hits = recall.memory_search("拿易拉罐", limit=3)
    assert hits.ok
    assert len(hits.observation["hits"]) >= 1


def test_lesson_recorded_on_act(tmp_path):
    recall = RecallService(_cfg(tmp_path))
    recall.on_task_start("x", "can_cola")
    recall.record_lesson(
        1,
        ActResult(ok=False, action="close_gripper", message="grasp_miss"),
        {},
    )
    lessons = recall.build_recall_snapshot()["recent_lessons"]
    assert lessons[0]["message"] == "grasp_miss"
