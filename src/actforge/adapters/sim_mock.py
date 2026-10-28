"""Deterministic mock physics for Phase 1 (SimBackend)."""

from __future__ import annotations

import math
from typing import Any

from actforge.adapters import sim_coupling_ops
from actforge.util.config import world_from_scene_cfg
from actforge.worldview.models import ActResult, Pose, SceneObject, WorldState


def can_grasp(ee: Pose, obj: SceneObject, xy_tol: float, z_tol: float) -> bool:
    if not obj.graspable:
        return False
    dist_xy = math.hypot(ee.x - obj.xyz.x, ee.y - obj.xyz.y)
    if dist_xy > xy_tol:
        return False
    if abs(ee.z - obj.xyz.z) > z_tol:
        return False
    return True


class MockSim:
    """Apply actuation actions to WorldState in place. Satisfies SimBackend."""

    def reset(self, scene_cfg: dict[str, Any] | WorldState) -> WorldState:
        if isinstance(scene_cfg, WorldState):
            return scene_cfg.model_copy(deep=True)
        return world_from_scene_cfg(scene_cfg)

    def restore_from_world(self, world: WorldState) -> None:
        """No engine state; WorldState itself is the source of truth."""
        return

    def apply(self, action: str, args: dict, world: WorldState) -> ActResult:
        handlers = {
            "list_objects": self._list_objects,
            "get_object_pose": self._get_object_pose,
            "move_above": self._move_above,
            "move_down": self._move_down,
            "close_gripper": self._close_gripper,
            "open_gripper": self._open_gripper,
            "lift": self._lift,
            "place_down": self._place_down,
            "place_home": self._place_home,
            "move_to": self._move_to,
            "return_home": self._return_home,
            "wipe_inner": self._wipe_inner,
            "measure_inner": self._measure_inner,
            "done": self._done,
        }
        handler = handlers.get(action)
        if handler is None:
            return ActResult(ok=False, action=action, message="unknown_action")
        return handler(world, args)

    def _sync_holding(self, world: WorldState) -> None:
        holding = world.robot.holding
        if not holding:
            return
        obj = world.objects.get(holding)
        if obj is None:
            return
        ee = world.robot.ee_pose
        obj.xyz = Pose(x=ee.x, y=ee.y, z=ee.z, yaw=obj.xyz.yaw)
        obj.attached_to = "ee"

    def _list_objects(self, world: WorldState, args: dict) -> ActResult:
        items = [
            {
                "id": o.id,
                "name": o.display_name,
                "x": o.xyz.x,
                "y": o.xyz.y,
                "z": o.xyz.z,
            }
            for o in world.objects.values()
        ]
        return ActResult(
            ok=True,
            action="list_objects",
            message=f"{len(items)} objects",
            observation={"objects": items},
        )

    def _get_object_pose(self, world: WorldState, args: dict) -> ActResult:
        oid = args.get("object_id")
        if not oid or oid not in world.objects:
            return ActResult(ok=False, action="get_object_pose", message="object_not_found")
        obj = world.objects[oid]
        return ActResult(
            ok=True,
            action="get_object_pose",
            message=f"pose of {oid}",
            observation={"object_id": oid, "xyz": obj.xyz.model_dump()},
        )

    def _move_above(self, world: WorldState, args: dict) -> ActResult:
        oid = args.get("object_id")
        if not oid or oid not in world.objects:
            return ActResult(ok=False, action="move_above", message="object_not_found")
        obj = world.objects[oid]
        z_offset = float(args.get("z_offset", world.motion_default_z_offset))
        # z = object center z + half height + offset (approach from above top)
        target_z = obj.xyz.z + obj.height / 2 + z_offset
        world.robot.ee_pose = Pose(x=obj.xyz.x, y=obj.xyz.y, z=target_z, yaw=0.0)
        self._sync_holding(world)
        ee = world.robot.ee_pose
        return ActResult(
            ok=True,
            action="move_above",
            message=f"ee moved above {oid}",
            observation={"ee": ee.model_dump()},
        )

    def _move_down(self, world: WorldState, args: dict) -> ActResult:
        delta_z = float(args.get("delta_z", 0.08))
        ee = world.robot.ee_pose
        new_z = max(world.table_z + 0.02, ee.z - delta_z)
        world.robot.ee_pose = Pose(x=ee.x, y=ee.y, z=new_z, yaw=ee.yaw)
        self._sync_holding(world)
        return ActResult(
            ok=True,
            action="move_down",
            message=f"ee lowered by {delta_z}",
            observation={"ee": world.robot.ee_pose.model_dump()},
        )

    def _close_gripper(self, world: WorldState, args: dict) -> ActResult:
        if world.robot.gripper == "closed":
            return ActResult(
                ok=True,
                action="close_gripper",
                message="already_closed",
                observation={"holding": world.robot.holding},
            )
        world.robot.gripper = "closed"
        if world.robot.holding is not None:
            return ActResult(
                ok=True,
                action="close_gripper",
                message="already_holding",
                observation={"holding": world.robot.holding},
            )

        ee = world.robot.ee_pose
        candidates: list[tuple[float, SceneObject]] = []
        for obj in world.objects.values():
            if can_grasp(ee, obj, world.grasp_xy_tolerance, world.grasp_z_tolerance):
                dist = math.hypot(ee.x - obj.xyz.x, ee.y - obj.xyz.y)
                candidates.append((dist, obj))

        if not candidates:
            return ActResult(
                ok=False,
                action="close_gripper",
                message="grasp_miss",
                observation={"holding": None},
            )

        candidates.sort(key=lambda t: t[0])
        chosen = candidates[0][1]
        world.robot.holding = chosen.id
        chosen.attached_to = "ee"
        self._sync_holding(world)
        return ActResult(
            ok=True,
            action="close_gripper",
            message=f"grasped_{chosen.id}",
            observation={"holding": chosen.id},
        )

    def _open_gripper(self, world: WorldState, args: dict) -> ActResult:
        holding = world.robot.holding
        world.robot.gripper = "open"
        if holding and holding in world.objects:
            obj = world.objects[holding]
            ee = world.robot.ee_pose
            # place on table at object resting height
            obj.xyz = Pose(x=ee.x, y=ee.y, z=obj.height / 2, yaw=obj.xyz.yaw)
            obj.attached_to = None
            world.robot.holding = None
            return ActResult(
                ok=True,
                action="open_gripper",
                message=f"released_{holding}",
                observation={"holding": None},
            )
        world.robot.holding = None
        return ActResult(
            ok=True,
            action="open_gripper",
            message="opened",
            observation={"holding": None},
        )

    def _lift(self, world: WorldState, args: dict) -> ActResult:
        delta_z = float(args.get("delta_z", 0.12))
        ee = world.robot.ee_pose
        world.robot.ee_pose = Pose(x=ee.x, y=ee.y, z=ee.z + delta_z, yaw=ee.yaw)
        self._sync_holding(world)
        return ActResult(
            ok=True,
            action="lift",
            message=f"lifted by {delta_z}",
            observation={"ee": world.robot.ee_pose.model_dump(), "holding": world.robot.holding},
        )

    def _place_down(self, world: WorldState, args: dict) -> ActResult:
        return sim_coupling_ops.place_down(world, args)

    def _place_home(self, world: WorldState, args: dict) -> ActResult:
        return sim_coupling_ops.place_home(world, args)

    def _move_to(self, world: WorldState, args: dict) -> ActResult:
        return sim_coupling_ops.move_to(world, args)

    def _return_home(self, world: WorldState, args: dict) -> ActResult:
        return sim_coupling_ops.return_home(world, args)

    def _wipe_inner(self, world: WorldState, args: dict) -> ActResult:
        return sim_coupling_ops.wipe_inner(world, args)

    def _measure_inner(self, world: WorldState, args: dict) -> ActResult:
        return sim_coupling_ops.measure_inner(world, args)

    def _done(self, world: WorldState, args: dict) -> ActResult:
        reason = args.get("reason", "model_claims_done")
        return ActResult(
            ok=True,
            action="done",
            message=str(reason),
            observation={
                "holding": world.robot.holding,
                "task_flags": dict(world.task_flags),
            },
        )
