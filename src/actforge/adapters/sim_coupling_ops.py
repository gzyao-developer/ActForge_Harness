"""Shared coupling wipe / measure / place semantics for Mock & PyBullet."""

from __future__ import annotations

import math

from actforge.worldview.models import ActResult, Pose, WorldState


def active_coupling_id(world: WorldState) -> str | None:
    """Resolve current workpiece's coupling object id."""
    oid = world.task_flags.get("current_coupling_id")
    if oid and oid in world.objects:
        return str(oid)
    wp = str(world.task_flags.get("current_workpiece") or "")
    wp_cfg = (world.coupling_cfg.get("workpieces") or {}).get(wp) or {}
    oid = wp_cfg.get("object_id")
    if oid and oid in world.objects:
        return str(oid)
    # Legacy single-coupling scenes
    if "coupling" in world.objects:
        return "coupling"
    return None


def _near_coupling(world: WorldState, tol_key: str, default_tol: float = 0.10) -> bool:
    cid = active_coupling_id(world)
    if not cid:
        return False
    coupling = world.objects[cid]
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
    cid = active_coupling_id(world)
    world.task_flags["coupling_wiped"] = True
    world.task_flags["wipe_count"] = int(world.task_flags.get("wipe_count", 0)) + 1
    world.task_flags["last_wiped_coupling"] = cid
    return ActResult(
        ok=True,
        action="wipe_inner",
        message=f"wiped_{cid or 'coupling'}_inner",
        observation={"coupling_wiped": True, "coupling_id": cid},
    )


def measure_inner(world: WorldState, args: dict) -> ActResult:
    if world.robot.holding != "ruler":
        return ActResult(ok=False, action="measure_inner", message="need_holding_ruler")
    if not _near_coupling(world, "measure_xy_tolerance"):
        return ActResult(ok=False, action="measure_inner", message="too_far_from_coupling")
    if not world.task_flags.get("measure_allowed", True):
        # Default True keeps LLM path usable; script sets False until review passes
        return ActResult(ok=False, action="measure_inner", message="measure_not_allowed")

    cid = active_coupling_id(world)
    if not cid or cid not in world.objects:
        return ActResult(ok=False, action="measure_inner", message="no_active_coupling")
    coupling = world.objects[cid]
    nominal = world.coupling_cfg.get("nominal_pitch_diameter_mm")
    if nominal is None:
        nominal = world.coupling_cfg.get("nominal_inner_diameter_mm")
    if nominal is None:
        inner = coupling.inner_radius or max(coupling.radius * 0.75, 0.01)
        nominal = round(inner * 2 * 1000, 1)
    else:
        nominal = float(nominal)

    wp = str(world.task_flags.get("current_workpiece") or "")
    wp_cfg = (world.coupling_cfg.get("workpieces") or {}).get(wp) or {}
    if "delta_d_mm" in args:
        delta = float(args["delta_d_mm"])
    elif "delta_d_mm" in wp_cfg:
        delta = float(wp_cfg["delta_d_mm"])
    else:
        delta = 0.0
    measured = round(nominal + delta, 3)

    world.task_flags["coupling_measured"] = True
    world.task_flags["nominal_d_mm"] = nominal
    world.task_flags["delta_d_mm"] = delta
    world.task_flags["measured_d_mm"] = measured
    world.task_flags["inner_diameter_mm"] = measured  # backward-compatible alias
    return ActResult(
        ok=True,
        action="measure_inner",
        message=f"measured_{measured}mm_delta_{delta:+.3f}",
        observation={
            "nominal_d_mm": nominal,
            "delta_d_mm": delta,
            "measured_d_mm": measured,
            "coupling_measured": True,
        },
    )
