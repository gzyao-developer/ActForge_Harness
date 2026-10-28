from pathlib import Path

from actforge.skillbook.loader import load_skill_file
from actforge.skillbook.types import SkillBody, SkillMeta, SkillbookState
from actforge.worldview.models import ActResult


def scan_skills(skills_dir: str | Path) -> list[SkillMeta]:
    root = Path(skills_dir)
    catalog: list[SkillMeta] = []
    if not root.exists():
        return catalog
    for skill_md in sorted(root.glob("**/SKILL.md")):
        parsed = load_skill_file(skill_md)
        if parsed is None:
            continue
        meta, _ = parsed
        catalog.append(meta)
    return catalog


class Skillbook:
    def __init__(self, skills_dir: str | Path):
        self.skills_dir = Path(skills_dir)
        self._bodies: dict[str, SkillBody] = {}
        self.state = SkillbookState()
        self.refresh()

    def refresh(self) -> None:
        catalog: list[SkillMeta] = []
        bodies: dict[str, SkillBody] = {}
        for skill_md in sorted(self.skills_dir.glob("**/SKILL.md")):
            parsed = load_skill_file(skill_md)
            if parsed is None:
                continue
            meta, body = parsed
            catalog.append(meta)
            bodies[meta.name] = body
        self.state.catalog = catalog
        self._bodies = bodies

    @property
    def catalog(self) -> list[SkillMeta]:
        return self.state.catalog

    @property
    def active(self) -> SkillBody | None:
        return self.state.active

    def reset_active(self) -> None:
        self.state.active = None

    def load(self, name: str) -> ActResult:
        body = self._bodies.get(name)
        if body is None:
            return ActResult(ok=False, action="load_skill", message="unknown_skill")
        self.state.active = body
        return ActResult(
            ok=True,
            action="load_skill",
            message=f"loaded_{name}",
            observation={"skill_name": name, "description": body.description},
        )
