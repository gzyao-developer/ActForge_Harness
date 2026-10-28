from pathlib import Path
from typing import Any

import yaml

from actforge.worldview.models import Pose, RobotState, SceneObject, WorldState


def _load_yaml(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return data


_DEFAULT_RGBA = {
    "can_cola": [0.85, 0.15, 0.15, 1.0],
    "cup_white": [0.92, 0.92, 0.95, 1.0],
    "coupling": [0.55, 0.58, 0.62, 1.0],
    "rag": [0.2, 0.75, 0.35, 1.0],
    "ruler": [0.85, 0.75, 0.2, 1.0],
}


def world_from_scene_cfg(cfg: dict[str, Any]) -> WorldState:
    table = cfg.get("table", {})
    robot_cfg = cfg.get("robot", {})
    ee = robot_cfg.get("ee_pose", {})
    grasp = cfg.get("grasp", {})
    motion = cfg.get("motion", {})
    coupling_cfg = dict(cfg.get("coupling") or {})

    objects: dict[str, SceneObject] = {}
    for item in cfg.get("objects", []):
        xyz = item.get("xyz", {})
        size = item.get("size") or {}
        oid = item["id"]
        shape = item.get("shape", "cylinder")
        height = float(item.get("height", size.get("z", 0.1)))
        objects[oid] = SceneObject(
            id=oid,
            label=item.get("label", oid),
            display_name=item.get("display_name", oid),
            xyz=Pose(
                x=float(xyz.get("x", 0)),
                y=float(xyz.get("y", 0)),
                z=float(xyz.get("z", 0)),
                yaw=float(item.get("yaw", 0)),
            ),
            radius=float(item.get("radius", 0.03)),
            height=height,
            graspable=bool(item.get("graspable", True)),
            shape=shape if shape in ("cylinder", "box", "ring") else "cylinder",
            size_x=float(size.get("x", item.get("radius", 0.03) * 2)),
            size_y=float(size.get("y", item.get("radius", 0.03) * 2)),
            size_z=float(size.get("z", height)),
            inner_radius=float(item.get("inner_radius", 0.0)),
            rgba=list(item.get("rgba") or _DEFAULT_RGBA.get(oid, [0.2, 0.6, 0.9, 1.0])),
        )

    home_ee = Pose(
        x=float(ee.get("x", 0)),
        y=float(ee.get("y", 0)),
        z=float(ee.get("z", 0.25)),
        yaw=float(ee.get("yaw", 0)),
    )
    object_homes = {oid: obj.xyz.model_copy(deep=True) for oid, obj in objects.items()}

    return WorldState(
        scene_id=cfg.get("scene_id", "unknown"),
        table_z=float(table.get("z", 0.0)),
        robot=RobotState(
            ee_pose=home_ee.model_copy(deep=True),
            gripper=robot_cfg.get("gripper", "open"),
            holding=robot_cfg.get("holding"),
        ),
        objects=objects,
        grasp_xy_tolerance=float(grasp.get("xy_tolerance", 0.03)),
        grasp_z_tolerance=float(grasp.get("z_tolerance", 0.04)),
        table_bounds={
            "x_min": float(table.get("x_min", -0.5)),
            "x_max": float(table.get("x_max", 0.5)),
            "y_min": float(table.get("y_min", -0.5)),
            "y_max": float(table.get("y_max", 0.5)),
        },
        motion_default_z_offset=float(motion.get("default_z_offset", 0.12)),
        task_flags={},
        coupling_cfg=coupling_cfg,
        home_ee=home_ee,
        object_homes=object_homes,
    )


def load_scene(path: str | Path) -> WorldState:
    return world_from_scene_cfg(_load_yaml(path))


def load_task(path: str | Path) -> dict[str, Any]:
    return _load_yaml(path)


def load_recall_config(path: str | Path) -> dict[str, Any]:
    return _load_yaml(path)


def resolve_goal_object_id(
    instruction: str,
    aliases: dict[str, list[str]] | None,
    default_id: str,
) -> str:
    """Rule-assisted goal id from natural language aliases (LLM remains primary)."""
    if not aliases:
        return default_id
    text = (instruction or "").lower()
    best_id = default_id
    best_len = -1
    for oid, words in aliases.items():
        for w in words or []:
            w_norm = str(w).lower()
            if w_norm and w_norm in text and len(w_norm) > best_len:
                best_id = oid
                best_len = len(w_norm)
    return best_id
