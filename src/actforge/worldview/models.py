from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class Pose(BaseModel):
    x: float
    y: float
    z: float
    yaw: float = 0.0


class SceneObject(BaseModel):
    id: str
    label: str
    display_name: str
    xyz: Pose
    radius: float = 0.03
    height: float = 0.1
    graspable: bool = True
    attached_to: Optional[str] = None
    shape: Literal["cylinder", "box", "ring"] = "cylinder"
    size_x: float = 0.06
    size_y: float = 0.06
    size_z: float = 0.02
    inner_radius: float = 0.0
    rgba: list[float] = Field(default_factory=lambda: [0.2, 0.6, 0.9, 1.0])


class RobotState(BaseModel):
    ee_pose: Pose
    gripper: Literal["open", "closed"] = "open"
    holding: Optional[str] = None


class WorldState(BaseModel):
    scene_id: str
    table_z: float
    robot: RobotState
    objects: dict[str, SceneObject]
    grasp_xy_tolerance: float = 0.03
    grasp_z_tolerance: float = 0.04
    table_bounds: dict[str, float] = Field(
        default_factory=lambda: {
            "x_min": -0.5,
            "x_max": 0.5,
            "y_min": -0.5,
            "y_max": 0.5,
        }
    )
    motion_default_z_offset: float = 0.12
    # Task progress flags (e.g. coupling wipe/measure)
    task_flags: dict[str, Any] = Field(default_factory=dict)
    coupling_cfg: dict[str, Any] = Field(default_factory=dict)
    # Initial poses for put-back / return-home
    home_ee: Optional[Pose] = None
    object_homes: dict[str, Pose] = Field(default_factory=dict)


class ActionIntent(BaseModel):
    thought: str = ""
    action: str
    args: dict[str, Any] = Field(default_factory=dict)


class ActResult(BaseModel):
    ok: bool
    action: str
    message: str = ""
    observation: dict[str, Any] = Field(default_factory=dict)


class GateResult(BaseModel):
    allowed: bool
    reason: str = ""


class VerifyResult(BaseModel):
    success: bool
    reason: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)


ALLOWED_ACTIONS = [
    "list_objects",
    "get_object_pose",
    "move_above",
    "move_down",
    "close_gripper",
    "open_gripper",
    "lift",
    "place_down",
    "place_home",
    "move_to",
    "return_home",
    "wipe_inner",
    "measure_inner",
    "load_skill",
    "note_write",
    "memory_search",
    "memory_write",
    "done",
]
