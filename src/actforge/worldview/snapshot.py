from typing import Any, Optional

from pydantic import BaseModel, Field

from actforge.worldview.models import ALLOWED_ACTIONS, ActResult, WorldState


class Snapshot(BaseModel):
    instruction: str
    goal_object_id: str
    step: int
    max_steps: int
    robot: dict[str, Any]
    objects: list[dict[str, Any]]
    last_result: Optional[dict[str, Any]] = None
    last_evaluation: Optional[dict[str, Any]] = None
    skill_catalog: list[dict[str, str]] = Field(default_factory=list)
    active_skill: Optional[dict[str, str]] = None
    recall: dict[str, Any] = Field(default_factory=dict)
    allowed_actions: list[str] = Field(default_factory=lambda: list(ALLOWED_ACTIONS))

    def to_compact_dict(self) -> dict[str, Any]:
        data = self.model_dump()
        if data.get("active_skill") and "body_excerpt" in data["active_skill"]:
            excerpt = data["active_skill"]["body_excerpt"]
            if len(excerpt) > 200:
                data["active_skill"]["body_excerpt"] = excerpt[:200] + "..."
        return data


def build_snapshot(
    instruction: str,
    world: WorldState,
    step: int,
    max_steps: int,
    last_result: Optional[ActResult],
    *,
    skillbook: Any = None,
    recall: Optional[dict[str, Any]] = None,
    goal_object_id: str = "",
    active_body_max: int = 2000,
    last_evaluation: Optional[dict[str, Any]] = None,
) -> Snapshot:
    objects = []
    for obj in world.objects.values():
        item = {
            "id": obj.id,
            "name": obj.display_name,
            "x": obj.xyz.x,
            "y": obj.xyz.y,
            "z": obj.xyz.z,
            "graspable": obj.graspable,
        }
        if obj.attached_to:
            item["attached_to"] = obj.attached_to
        objects.append(item)

    skill_catalog: list[dict[str, str]] = []
    active_skill = None
    if skillbook is not None:
        skill_catalog = [
            {"name": m.name, "description": m.description} for m in skillbook.catalog
        ]
        if skillbook.active is not None:
            body = skillbook.active.body
            if len(body) > active_body_max:
                body = body[:active_body_max] + "\n...(truncated)"
            active_skill = {
                "name": skillbook.active.name,
                "body_excerpt": body,
            }

    return Snapshot(
        instruction=instruction,
        goal_object_id=goal_object_id,
        step=step,
        max_steps=max_steps,
        robot={
            "ee": world.robot.ee_pose.model_dump(),
            "gripper": world.robot.gripper,
            "holding": world.robot.holding,
        },
        objects=objects,
        last_result=last_result.model_dump() if last_result else None,
        last_evaluation=last_evaluation,
        skill_catalog=skill_catalog,
        active_skill=active_skill,
        recall={
            **(recall or {}),
            "task_flags": dict(world.task_flags or {}),
            "object_homes": {
                oid: pose.model_dump() for oid, pose in (world.object_homes or {}).items()
            },
            "home_ee": world.home_ee.model_dump() if world.home_ee else None,
        },
        allowed_actions=list(ALLOWED_ACTIONS),
    )
