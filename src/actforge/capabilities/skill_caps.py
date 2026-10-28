from typing import Any

from actforge.worldview.models import ActResult, WorldState


class LoadSkillCapability:
    name = "load_skill"

    def execute(
        self, world: WorldState, args: dict, ctx: dict[str, Any] | None = None
    ) -> ActResult:
        ctx = ctx or {}
        skillbook = ctx.get("skillbook")
        if skillbook is None:
            return ActResult(ok=False, action=self.name, message="no_skillbook")
        skill_name = args.get("skill_name") or args.get("name")
        if not skill_name:
            return ActResult(ok=False, action=self.name, message="missing_skill_name")
        return skillbook.load(str(skill_name))
