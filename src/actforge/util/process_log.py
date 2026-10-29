"""Concise human-readable process log for a run."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TextIO


class ProcessLog:
    """Write short process lines to a text file (and optionally stdout)."""

    def __init__(self, path: str | Path, *, echo: bool = True):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.echo = echo
        self._fh: TextIO = self.path.open("w", encoding="utf-8")

    def line(self, text: str = "") -> None:
        self._fh.write(text + "\n")
        self._fh.flush()
        if self.echo:
            print(text)

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self) -> "ProcessLog":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def format_inspection_line(insp: dict[str, Any]) -> str:
    wp = insp.get("workpiece") or ""
    prefix = f"[接箍{wp}] " if wp else ""
    return (
        f"{prefix}"
        f"{insp.get('event', '')} | "
        f"{insp.get('feedback', '')} | "
        f"{insp.get('disposition', '')}"
    )


def write_inspection_summary(plog: ProcessLog, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    plog.line("---- 关键事件 ----")
    plog.line(f"{'t/s':>4}  {'事件':<8}  {'反馈':<28}  {'处置'}")
    for row in rows:
        plog.line(
            f"{int(row.get('time_s', 0)):>4}  "
            f"{str(row.get('event', '')):<8}  "
            f"{str(row.get('feedback', '')):<28}  "
            f"{row.get('disposition', '')}"
        )
    plog.line("----------------")
