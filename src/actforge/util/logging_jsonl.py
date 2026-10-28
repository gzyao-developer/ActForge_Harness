import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class EventLog:
    def __init__(self, run_id: str, path: str | Path):
        self.run_id = run_id
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")

    def emit(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        record = {
            "ts": _utc_now(),
            "run_id": self.run_id,
            "type": event_type,
            "payload": payload or {},
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
