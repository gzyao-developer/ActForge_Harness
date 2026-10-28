from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from actforge.worldview.models import ActResult


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Lesson(BaseModel):
    ts: str
    step: int
    action: str
    ok: bool
    message: str = ""
    args_digest: str = ""


class ToolExperienceStore:
    def __init__(
        self,
        recent_k: int = 5,
        persist_jsonl: str | Path | None = None,
        persist_on_act: bool = True,
    ):
        self.recent_k = recent_k
        self.persist_jsonl = Path(persist_jsonl) if persist_jsonl else None
        self.persist_on_act = persist_on_act
        self._lessons: list[Lesson] = []

    def clear(self) -> None:
        self._lessons.clear()

    def record(self, step: int, act_result: ActResult, args: dict[str, Any]) -> Lesson:
        digest = ""
        if args:
            try:
                digest = json.dumps(args, ensure_ascii=False)[:120]
            except TypeError:
                digest = str(args)[:120]
        lesson = Lesson(
            ts=_utc_now(),
            step=step,
            action=act_result.action,
            ok=act_result.ok,
            message=act_result.message,
            args_digest=digest,
        )
        self._lessons.append(lesson)
        if len(self._lessons) > max(self.recent_k * 4, 20):
            self._lessons = self._lessons[-self.recent_k * 4 :]
        if self.persist_on_act and self.persist_jsonl:
            self.persist_jsonl.parent.mkdir(parents=True, exist_ok=True)
            with open(self.persist_jsonl, "a", encoding="utf-8") as f:
                f.write(lesson.model_dump_json() + "\n")
        return lesson

    def recent(self) -> list[dict[str, Any]]:
        items = self._lessons[-self.recent_k :]
        return [
            {"action": x.action, "ok": x.ok, "message": x.message, "step": x.step}
            for x in items
        ]

    def flush(self) -> None:
        # already appended per-act when persist_on_act; noop placeholder
        return
