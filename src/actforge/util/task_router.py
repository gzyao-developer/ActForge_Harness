from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_tasks_catalog(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Invalid tasks catalog: {path}")
    return data


def infer_task_id(instruction: str, catalog: dict[str, Any]) -> str:
    text = instruction or ""
    text_l = text.lower()
    for rule in catalog.get("routing") or []:
        tid = rule.get("id")
        for kw in rule.get("keywords") or []:
            kw_s = str(kw)
            if kw_s.lower() in text_l or kw_s in text:
                return str(tid)
    defaults = catalog.get("defaults") or {}
    if "pick_can" in defaults:
        return "pick_can"
    if defaults:
        return next(iter(defaults.keys()))
    return "pick_can"


def resolve_task_preset(
    instruction: str,
    catalog_path: str | Path,
    *,
    task_id: str | None = None,
) -> tuple[str, dict[str, str]]:
    """Return (task_id, {scene, task, prompt})."""
    catalog = load_tasks_catalog(catalog_path)
    tid = task_id or infer_task_id(instruction, catalog)
    defaults = catalog.get("defaults") or {}
    if tid not in defaults:
        tid = "pick_can" if "pick_can" in defaults else next(iter(defaults))
    preset = dict(defaults[tid])
    return tid, preset
