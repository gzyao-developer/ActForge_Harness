from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class DurableItem(BaseModel):
    id: str
    text: str
    tags: list[str] = Field(default_factory=list)
    created_at: str = ""


def _tokenize(text: str) -> set[str]:
    text = text.lower()
    tokens: set[str] = set()
    for m in re.finditer(r"[a-z0-9_]+", text):
        tokens.add(m.group(0))
    # Chinese bigrams + unigrams for short queries
    cn_chars = re.findall(r"[\u4e00-\u9fff]", text)
    for i, ch in enumerate(cn_chars):
        tokens.add(ch)
        if i + 1 < len(cn_chars):
            tokens.add(cn_chars[i] + cn_chars[i + 1])
    return tokens


def score_query(query: str, text: str) -> float:
    q = query.strip().lower()
    t = text.lower()
    if not q or not t:
        return 0.0
    # substring bonus
    bonus = 0.0
    if q in t:
        bonus = 0.5
    q_tokens = _tokenize(query)
    t_tokens = _tokenize(text)
    if not q_tokens or not t_tokens:
        return bonus
    inter = len(q_tokens & t_tokens)
    union = len(q_tokens | t_tokens)
    jaccard = inter / union if union else 0.0
    return jaccard + bonus


class DurableStore:
    def __init__(self, dir_path: str | Path, max_write_chars: int = 500):
        self.dir = Path(dir_path)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.max_write_chars = max_write_chars

    def _parse_file(self, path: Path) -> DurableItem | None:
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return None
        meta: dict[str, Any] = {}
        body = raw
        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                try:
                    meta = yaml.safe_load(parts[1]) or {}
                except yaml.YAMLError:
                    meta = {}
                body = parts[2].strip()
        item_id = str(meta.get("id") or path.stem)
        tags = meta.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        return DurableItem(
            id=item_id,
            text=body.strip(),
            tags=list(tags),
            created_at=str(meta.get("created_at", "")),
        )

    def list_all(self) -> list[DurableItem]:
        items: list[DurableItem] = []
        for path in sorted(self.dir.glob("*.md")):
            item = self._parse_file(path)
            if item and item.text:
                items.append(item)
        for path in sorted(self.dir.glob("*.json")):
            try:
                import json

                data = json.loads(path.read_text(encoding="utf-8"))
                items.append(DurableItem.model_validate(data))
            except Exception:
                continue
        return items

    def search(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        scored: list[tuple[float, DurableItem]] = []
        for item in self.list_all():
            s = score_query(query, item.text)
            if s > 0:
                scored.append((s, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        hits = []
        for s, item in scored[:limit]:
            hits.append({"id": item.id, "text": item.text, "score": round(s, 3), "tags": item.tags})
        return hits

    def write(self, text: str, tags: list[str] | None = None) -> DurableItem:
        text = text.strip()
        if len(text) > self.max_write_chars:
            text = text[: self.max_write_chars]
        item_id = f"d{uuid.uuid4().hex[:8]}"
        created = _utc_now()
        tag_list = tags or []
        content = (
            f"---\n"
            f"id: {item_id}\n"
            f"tags: [{', '.join(tag_list)}]\n"
            f"created_at: {created}\n"
            f"---\n\n"
            f"{text}\n"
        )
        path = self.dir / f"{item_id}.md"
        path.write_text(content, encoding="utf-8")
        return DurableItem(id=item_id, text=text, tags=tag_list, created_at=created)
