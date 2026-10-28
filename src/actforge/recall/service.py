from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from actforge.recall.durable import DurableStore
from actforge.recall.task_notes import TaskNotesStore
from actforge.recall.tool_experience import ToolExperienceStore
from actforge.worldview.models import ActResult, VerifyResult


class TaskOutcome(BaseModel):
    status: str
    steps: int = 0
    reason: str = ""
    verify: Optional[VerifyResult] = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class RecallService:
    def __init__(self, cfg: dict[str, Any], event_log: Any = None):
        notes_cfg = cfg.get("task_notes", {})
        durable_cfg = cfg.get("durable", {})
        exp_cfg = cfg.get("tool_experience", {})
        self.on_success_cfg = cfg.get("on_task_success", {})

        self.task_notes = TaskNotesStore(max_items=int(notes_cfg.get("max_items", 20)))
        self.durable = DurableStore(
            dir_path=durable_cfg.get("dir", "data/recall/durable"),
            max_write_chars=int(durable_cfg.get("max_write_chars", 500)),
        )
        self.tool_experience = ToolExperienceStore(
            recent_k=int(exp_cfg.get("recent_k", 5)),
            persist_jsonl=exp_cfg.get("persist_jsonl"),
            persist_on_act=bool(exp_cfg.get("persist_on_act", True)),
        )
        self.auto_retrieve = bool(durable_cfg.get("auto_retrieve_each_step", True))
        self.top_k = int(durable_cfg.get("top_k", 3))
        self.max_write_chars = int(durable_cfg.get("max_write_chars", 500))
        self._durable_hits: list[dict[str, Any]] = []
        self._instruction = ""
        self._goal_object_id = ""
        self.event_log = event_log

    def on_task_start(self, instruction: str, goal_object_id: str) -> None:
        self.task_notes.clear()
        self.tool_experience.clear()
        self._instruction = instruction
        self._goal_object_id = goal_object_id
        query = f"{instruction} {goal_object_id}".strip()
        self._durable_hits = self.durable.search(query, limit=self.top_k)

    def build_recall_snapshot(self) -> dict[str, Any]:
        if self.auto_retrieve and self._instruction:
            query = f"{self._instruction} {self._goal_object_id}".strip()
            self._durable_hits = self.durable.search(query, limit=self.top_k)
        return {
            "task_notes": self.task_notes.list_texts(),
            "durable_hits": list(self._durable_hits),
            "recent_lessons": self.tool_experience.recent(),
        }

    def note_write(self, text: str) -> ActResult:
        text = (text or "").strip()
        if not text:
            return ActResult(ok=False, action="note_write", message="empty_text")
        self.task_notes.write(text)
        if self.event_log:
            self.event_log.emit("memory.note_written", {"text": text[:200]})
        return ActResult(
            ok=True,
            action="note_write",
            message="note_saved",
            observation={"count": len(self.task_notes.notes)},
        )

    def memory_search(self, query: str, limit: int = 3) -> ActResult:
        hits = self.durable.search(query, limit=limit)
        self._durable_hits = hits
        if self.event_log:
            self.event_log.emit("memory.searched", {"query": query, "hits": len(hits)})
        return ActResult(
            ok=True,
            action="memory_search",
            message=f"hits={len(hits)}",
            observation={"hits": hits},
        )

    def memory_write(self, text: str, tags: list[str] | None = None) -> ActResult:
        text = (text or "").strip()
        if not text:
            return ActResult(ok=False, action="memory_write", message="empty_text")
        if len(text) > self.max_write_chars:
            return ActResult(ok=False, action="memory_write", message="text_too_long")
        item = self.durable.write(text, tags=tags)
        if self.event_log:
            self.event_log.emit("memory.durable_written", {"id": item.id})
        return ActResult(
            ok=True,
            action="memory_write",
            message=f"written_{item.id}",
            observation={"id": item.id},
        )

    def record_lesson(self, step: int, act_result: ActResult, args: dict) -> None:
        self.tool_experience.record(step, act_result, args)

    def on_task_end(
        self, outcome: TaskOutcome, instruction: str, goal_object_id: str
    ) -> None:
        self.tool_experience.flush()
        if (
            outcome.status == "success"
            and self.on_success_cfg.get("write_durable_summary", True)
        ):
            tmpl = self.on_success_cfg.get(
                "summary_template",
                "任务成功：{instruction}；目标={goal_object_id}；步数={steps}",
            )
            summary = tmpl.format(
                instruction=instruction,
                goal_object_id=goal_object_id,
                steps=outcome.steps,
            )
            item = self.durable.write(summary, tags=["task_success", goal_object_id])
            if self.event_log:
                self.event_log.emit(
                    "memory.durable_written",
                    {"id": item.id, "kind": "task_summary"},
                )
