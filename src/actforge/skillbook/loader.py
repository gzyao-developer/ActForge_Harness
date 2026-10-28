from pathlib import Path
from typing import Any

import yaml

from actforge.skillbook.types import SkillBody, SkillMeta


def parse_skill_md(path: Path) -> tuple[SkillMeta, SkillBody] | None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        meta_raw: dict[str, Any] = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return None
    name = str(meta_raw.get("name", "")).strip()
    description = str(meta_raw.get("description", "")).strip()
    if not name:
        return None
    body = parts[2].strip()
    meta = SkillMeta(name=name, description=description, path=str(path))
    skill_body = SkillBody(name=name, description=description, body=body)
    return meta, skill_body


def load_skill_file(path: Path) -> tuple[SkillMeta, SkillBody] | None:
    try:
        return parse_skill_md(path)
    except OSError:
        return None
