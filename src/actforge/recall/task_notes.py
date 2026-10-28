from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TaskNote(BaseModel):
    ts: str
    text: str


class TaskNotesStore:
    def __init__(self, max_items: int = 20):
        self.max_items = max_items
        self._notes: list[TaskNote] = []

    def clear(self) -> None:
        self._notes.clear()

    def write(self, text: str) -> TaskNote:
        note = TaskNote(ts=_utc_now(), text=text)
        self._notes.append(note)
        if len(self._notes) > self.max_items:
            self._notes = self._notes[-self.max_items :]
        return note

    def list_texts(self) -> list[str]:
        return [n.text for n in self._notes]

    @property
    def notes(self) -> list[TaskNote]:
        return list(self._notes)
