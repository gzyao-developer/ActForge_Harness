from typing import Any

from actforge.worldview.models import ActResult, WorldState


class NoteWriteCapability:
    name = "note_write"

    def execute(
        self, world: WorldState, args: dict, ctx: dict[str, Any] | None = None
    ) -> ActResult:
        recall = (ctx or {}).get("recall")
        if recall is None:
            return ActResult(ok=False, action=self.name, message="no_recall")
        return recall.note_write(str(args.get("text", "")))


class MemorySearchCapability:
    name = "memory_search"

    def execute(
        self, world: WorldState, args: dict, ctx: dict[str, Any] | None = None
    ) -> ActResult:
        recall = (ctx or {}).get("recall")
        if recall is None:
            return ActResult(ok=False, action=self.name, message="no_recall")
        query = str(args.get("query", ""))
        limit = int(args.get("limit", 3))
        return recall.memory_search(query, limit=limit)


class MemoryWriteCapability:
    name = "memory_write"

    def execute(
        self, world: WorldState, args: dict, ctx: dict[str, Any] | None = None
    ) -> ActResult:
        recall = (ctx or {}).get("recall")
        if recall is None:
            return ActResult(ok=False, action=self.name, message="no_recall")
        tags = args.get("tags")
        if tags is not None and not isinstance(tags, list):
            tags = [str(tags)]
        return recall.memory_write(str(args.get("text", "")), tags=tags)
