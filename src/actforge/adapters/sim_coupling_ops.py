"""Shared coupling wipe / measure / place semantics for Mock & PyBullet."""

from __future__ import annotations

import math

from actforge.worldview.models import ActResult, Pose, WorldState


def _near_coupling(world: WorldState, tol_key: str, default_tol: float = 0.10) -> bool:
    coupling = world.objects.get("coupling")
    if coupling is None:
        return False
    ee = world.robot.ee_pose
    tol = float(world.coupling_cfg.get(tol_key, default_tol))
    return math.hypot(ee.x - coupling.xyz.x, ee.y - coupling.xyz.y) <= tol


def place_down(world: WorldState, args: dict) -> ActResult:
    """Release held object onto table at EE projection (or explicit x,y)."""
    holding = world.robot.holding
    if not holding or holding not in world.objects:
        world.robot.gripper = "open"
        return ActResult(ok=False, action="place_down", message="nothing_to_place")

    obj = world.objects[holding]
    ee = world.robot.ee_pose
    x = float(args.get("x", ee.x))
    y = float(args.get("y", ee.y))
    yaw = float(args.get("yaw", obj.xyz.yaw))
    half_h = obj.height / 2 if obj.shape != "box" else obj.size_z / 2
    z = float(args.get("z", world.table_z + max(half_h, 0.01)))
    obj.xyz = Pose(x=x, y=y, z=z, yaw=yaw)
    obj.attached_to = None
    world.robot.holding = None
    world.robot.gripper = "open"
    return ActResult(
        ok=True,
        action="place_down",
        message=f"placed_{holding}",
        observation={"placed": holding, "xyz": obj.xyz.model_dump()},
    )


def place_home(world: WorldState, args: dict) -> ActResult:
    """Put held object back to its recorded home pose on the table."""
    holding = world.robot.holding
    if not holding or holding not in world.objects:
        return ActResult(ok=False, action="place_home", message="nothing_to_place")
    home = world.object_homes.get(holding)
    if home is None:
        return ActResult(ok=False, action="place_home", message="no_home_pose")
    held_id = holding
    result = place_down(
        world,
        {"x": home.x, "y": home.y, "z": home.z, "yaw": home.yaw},
    )
    if result.ok:
        result.action = "place_home"
        result.message = f"placed_home_{held_id}"
    else:
        result.action = "place_home"
    return result


def return_home(world: WorldState, args: dict) -> ActResult:
    """Return EE to initial pose (held object follows if any)."""
    if world.home_ee is None:
        return ActResult(ok=False, action="return_home", message="no_home_ee")
    world.robot.ee_pose = world.home_ee.model_copy(deep=True)
    # Keep gripper state; if empty prefer open
    if world.robot.holding is None:
        world.robot.gripper = "open"
    holding = world.robot.holding
    if holding and holding in world.objects:
        ee = world.robot.ee_pose
        obj = world.objects[holding]
        obj.xyz = Pose(x=ee.x, y=ee.y, z=ee.z, yaw=obj.xyz.yaw)
        obj.attached_to = "ee"
    world.task_flags["returned_home"] = True
    return ActResult(
        ok=True,
        action="return_home",
        message="ee_at_home",
        observation={"ee": world.robot.ee_pose.model_dump(), "holding": holding},
    )


def move_to(world: WorldState, args: dict) -> ActResult:
    """Move EE to an absolute pose (used to approach object home slots)."""
    ee = world.robot.ee_pose
    x = float(args.get("x", ee.x))
    y = float(args.get("y", ee.y))
    z = float(args.get("z", ee.z))
    yaw = float(args.get("yaw", ee.yaw))
    world.robot.ee_pose = Pose(x=x, y=y, z=z, yaw=yaw)
    holding = world.robot.holding
    if holding and holding in world.objects:
        obj = world.objects[holding]
        obj.xyz = Pose(x=x, y=y, z=z, yaw=obj.xyz.yaw)
        obj.attached_to = "ee"
    return ActResult(
        ok=True,
        action="move_to",
        message=f"ee_to_({x:.2f},{y:.2f},{z:.2f})",
        observation={"ee": world.robot.ee_pose.model_dump()},
    )


def wipe_inner(world: WorldState, args: dict) -> ActResult:
    if world.robot.holding != "rag":
        return ActResult(ok=False, action="wipe_inner", message="need_holding_rag")
    if not _near_coupling(world, "wipe_xy_tolerance"):
        return ActResult(ok=False, action="wipe_inner", message="too_far_from_coupling")
    world.task_flags["coupling_wiped"] = True
    world.task_flags["wipe_count"] = int(world.task_flags.get("wipe_count", 0)) + 1
    return ActResult(
        ok=True,
        action="wipe_inner",
        message="wiped_coupling_inner",
        observation={"coupling_wiped": True},
    )


def measure_inner(world: WorldState, args: dict) -> ActResult:
    if world.robot.holding != "ruler":
        return ActResult(ok=False, action="measure_inner", message="need_holding_ruler")
    if not _near_coupling(world, "measure_xy_tolerance"):
        return ActResult(ok=False, action="measure_inner", message="too_far_from_coupling")
    coupling = world.objects["coupling"]
    # Prefer configured nominal diameter; else derive from inner_radius
    mm = world.coupling_cfg.get("nominal_inner_diameter_mm")
    if mm is None:
        inner = coupling.inner_radius or max(coupling.radius * 0.75, 0.01)
        mm = round(inner * 2 * 1000, 1)
    else:
        mm = float(mm)
    world.task_flags["coupling_measured"] = True
    world.task_flags["inner_diameter_mm"] = mm
    return ActResult(
        ok=True,
        action="measure_inner",
        message=f"measured_{mm}mm",
        observation={"inner_diameter_mm": mm, "coupling_measured": True},
    )
