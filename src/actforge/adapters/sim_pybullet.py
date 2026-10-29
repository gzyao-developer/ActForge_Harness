"""PyBullet simulation backend (Phase 2).

Objects are dynamic rigid bodies with gravity/contact.
The gripper is a kinematic end-effector (two fingers) driven by the same
high-level actions as MockSim (move_above / move_down / close / lift).
Successful grasps create a fixed constraint so the object follows the EE
through the physics engine — a common teaching pattern, much richer than Mock.
"""

from __future__ import annotations

import math
import time
from typing import Any, Optional

from actforge.adapters import sim_coupling_ops
from actforge.util.config import world_from_scene_cfg
from actforge.worldview.models import ActResult, Pose, SceneObject, WorldState

try:
    import pybullet as p
    import pybullet_data

    HAS_PYBULLET = True
except ImportError:  # pragma: no cover
    p = None  # type: ignore
    pybullet_data = None  # type: ignore
    HAS_PYBULLET = False


def require_pybullet() -> None:
    if not HAS_PYBULLET:
        raise ImportError(
            "pybullet is not installed. Run: pip install 'actforge[pybullet]' "
            "or: pip install pybullet"
        )


class PyBulletSim:
    """SimBackend backed by PyBullet physics."""

    def __init__(
        self,
        gui: bool = False,
        timestep: float = 1.0 / 240.0,
        steps_per_action: int = 90,
        real_time: bool = False,
    ):
        require_pybullet()
        self.gui = gui
        self.timestep = timestep
        self.steps_per_action = steps_per_action
        self.real_time = real_time
        self.client_id: int | None = None
        self._obj_body: dict[str, int] = {}
        self._ee_body: int | None = None
        self._finger_l: int | None = None
        self._finger_r: int | None = None
        self._constraint_id: int | None = None
        self._holding_id: str | None = None
        self._gripper_open_gap = 0.08
        self._gripper_closed_gap = 0.0
        self._world: WorldState | None = None

    # --- lifecycle -----------------------------------------------------

    def close(self) -> None:
        if self.client_id is not None and HAS_PYBULLET:
            try:
                p.disconnect(physicsClientId=self.client_id)
            except Exception:  # noqa: BLE001
                pass
            self.client_id = None

    def __del__(self) -> None:  # pragma: no cover
        self.close()

    def reset(self, scene_cfg: dict[str, Any] | WorldState) -> WorldState:
        require_pybullet()
        self.close()
        mode = p.GUI if self.gui else p.DIRECT
        self.client_id = p.connect(mode)
        p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=self.client_id)
        p.resetSimulation(physicsClientId=self.client_id)
        p.setGravity(0, 0, -9.81, physicsClientId=self.client_id)
        p.setTimeStep(self.timestep, physicsClientId=self.client_id)
        if self.gui:
            p.configureDebugVisualizer(p.COV_ENABLE_GUI, 0, physicsClientId=self.client_id)
            p.resetDebugVisualizerCamera(
                cameraDistance=1.2,
                cameraYaw=50,
                cameraPitch=-35,
                cameraTargetPosition=[0.1, 0.0, 0.1],
                physicsClientId=self.client_id,
            )

        if isinstance(scene_cfg, WorldState):
            world = scene_cfg.model_copy(deep=True)
        else:
            world = world_from_scene_cfg(scene_cfg)

        cid = self.client_id
        p.loadURDF("plane.urdf", physicsClientId=cid)

        # Table as a box (top surface ≈ table_z)
        table_thickness = 0.04
        table_z = world.table_z
        table_half = [
            (world.table_bounds["x_max"] - world.table_bounds["x_min"]) / 2,
            (world.table_bounds["y_max"] - world.table_bounds["y_min"]) / 2,
            table_thickness / 2,
        ]
        table_center = [
            (world.table_bounds["x_min"] + world.table_bounds["x_max"]) / 2,
            (world.table_bounds["y_min"] + world.table_bounds["y_max"]) / 2,
            table_z - table_thickness / 2,
        ]
        table_col = p.createCollisionShape(p.GEOM_BOX, halfExtents=table_half, physicsClientId=cid)
        table_vis = p.createVisualShape(
            p.GEOM_BOX, halfExtents=table_half, rgbaColor=[0.55, 0.4, 0.25, 1], physicsClientId=cid
        )
        p.createMultiBody(
            baseMass=0,
            baseCollisionShapeIndex=table_col,
            baseVisualShapeIndex=table_vis,
            basePosition=table_center,
            physicsClientId=cid,
        )

        self._obj_body.clear()
        for oid, obj in world.objects.items():
            half_h = max(obj.height / 2, obj.size_z / 2, 0.005)
            z = table_z + half_h
            obj.xyz = Pose(x=obj.xyz.x, y=obj.xyz.y, z=z, yaw=obj.xyz.yaw)
            rgba = obj.rgba if len(obj.rgba) == 4 else [0.2, 0.6, 0.9, 1.0]
            if obj.shape == "box":
                half = [
                    max(obj.size_x / 2, 0.005),
                    max(obj.size_y / 2, 0.005),
                    max(obj.size_z / 2, 0.005),
                ]
                col = p.createCollisionShape(p.GEOM_BOX, halfExtents=half, physicsClientId=cid)
                vis = p.createVisualShape(
                    p.GEOM_BOX, halfExtents=half, rgbaColor=rgba, physicsClientId=cid
                )
            elif obj.shape == "ring":
                # Approximate coupling as a short wide cylinder (visual stand-in for a ring)
                radius = max(obj.radius, 0.03)
                col = p.createCollisionShape(
                    p.GEOM_CYLINDER, radius=radius, height=obj.height, physicsClientId=cid
                )
                vis = p.createVisualShape(
                    p.GEOM_CYLINDER,
                    radius=radius,
                    length=obj.height,
                    rgbaColor=rgba,
                    physicsClientId=cid,
                )
            else:
                radius = max(obj.radius, 0.02)
                col = p.createCollisionShape(
                    p.GEOM_CYLINDER, radius=radius, height=obj.height, physicsClientId=cid
                )
                vis = p.createVisualShape(
                    p.GEOM_CYLINDER,
                    radius=radius,
                    length=obj.height,
                    rgbaColor=rgba,
                    physicsClientId=cid,
                )
            mass = 0.0 if not obj.graspable else 0.2
            body = p.createMultiBody(
                baseMass=mass,
                baseCollisionShapeIndex=col,
                baseVisualShapeIndex=vis,
                basePosition=[obj.xyz.x, obj.xyz.y, z],
                physicsClientId=cid,
            )
            p.changeDynamics(
                body,
                -1,
                lateralFriction=1.2,
                spinningFriction=0.01,
                rollingFriction=0.01,
                physicsClientId=cid,
            )
            self._obj_body[oid] = body

        self._create_gripper(world.robot.ee_pose)
        # Kinematic gripper must not shove dynamic objects while approaching
        self._set_gripper_object_collisions(enable=False)
        self._constraint_id = None
        self._holding_id = None
        world.robot.holding = None
        world.robot.gripper = "open"
        self._set_finger_gap(self._gripper_open_gap)
        self._settle(40)
        # Snap objects back to configured poses after settle (table contact jitter)
        for oid, obj in world.objects.items():
            body = self._obj_body[oid]
            p.resetBasePositionAndOrientation(
                body,
                [obj.xyz.x, obj.xyz.y, obj.xyz.z],
                p.getQuaternionFromEuler([0, 0, obj.xyz.yaw]),
                physicsClientId=cid,
            )
            p.resetBaseVelocity(body, [0, 0, 0], [0, 0, 0], physicsClientId=cid)
        self._sync_world(world)
        # Refresh home poses after physics settle (authoritative put-back targets)
        if world.home_ee is None:
            world.home_ee = world.robot.ee_pose.model_copy(deep=True)
        world.object_homes = {
            oid: obj.xyz.model_copy(deep=True) for oid, obj in world.objects.items()
        }
        self._world = world
        return world

    def _create_gripper(self, ee: Pose) -> None:
        cid = self.client_id
        assert cid is not None
        # Palm
        palm_half = [0.04, 0.02, 0.02]
        palm_col = p.createCollisionShape(p.GEOM_BOX, halfExtents=palm_half, physicsClientId=cid)
        palm_vis = p.createVisualShape(
            p.GEOM_BOX, halfExtents=palm_half, rgbaColor=[0.15, 0.15, 0.18, 1], physicsClientId=cid
        )
        self._ee_body = p.createMultiBody(
            baseMass=0,  # kinematic
            baseCollisionShapeIndex=palm_col,
            baseVisualShapeIndex=palm_vis,
            basePosition=[ee.x, ee.y, ee.z],
            physicsClientId=cid,
        )
        # Fingers as separate kinematic boxes parented via constraint to palm
        finger_half = [0.01, 0.01, 0.04]
        fcol = p.createCollisionShape(p.GEOM_BOX, halfExtents=finger_half, physicsClientId=cid)
        fvis_l = p.createVisualShape(
            p.GEOM_BOX, halfExtents=finger_half, rgbaColor=[0.3, 0.3, 0.35, 1], physicsClientId=cid
        )
        fvis_r = p.createVisualShape(
            p.GEOM_BOX, halfExtents=finger_half, rgbaColor=[0.3, 0.3, 0.35, 1], physicsClientId=cid
        )
        self._finger_l = p.createMultiBody(
            baseMass=0,
            baseCollisionShapeIndex=fcol,
            baseVisualShapeIndex=fvis_l,
            basePosition=[ee.x, ee.y - 0.04, ee.z - 0.04],
            physicsClientId=cid,
        )
        self._finger_r = p.createMultiBody(
            baseMass=0,
            baseCollisionShapeIndex=fcol,
            baseVisualShapeIndex=fvis_r,
            basePosition=[ee.x, ee.y + 0.04, ee.z - 0.04],
            physicsClientId=cid,
        )

    def _gripper_bodies(self) -> list[int]:
        bodies = []
        for b in (self._ee_body, self._finger_l, self._finger_r):
            if b is not None:
                bodies.append(b)
        return bodies

    def _set_gripper_object_collisions(self, enable: bool) -> None:
        """Disable approach collisions so the kinematic EE does not push cans."""
        cid = self._cid()
        flag = 1 if enable else 0
        for gb in self._gripper_bodies():
            for body in self._obj_body.values():
                p.setCollisionFilterPair(gb, body, -1, -1, flag, physicsClientId=cid)

    # --- helpers -------------------------------------------------------

    def _cid(self) -> int:
        if self.client_id is None:
            raise RuntimeError("PyBulletSim not reset")
        return self.client_id

    def _step(self, n: int | None = None) -> None:
        cid = self._cid()
        n = self.steps_per_action if n is None else n
        for _ in range(n):
            p.stepSimulation(physicsClientId=cid)
            if self.gui and self.real_time:
                time.sleep(self.timestep)

    def _settle(self, n: int = 30) -> None:
        self._step(n)

    def _viz_wait(self, seconds: float) -> None:
        """Wall-clock pause only with --gui --real-time (otherwise keep demo snappy)."""
        if not self.gui or not self.real_time or seconds <= 0:
            if self.gui and seconds > 0:
                self._step(max(1, int(seconds * 30)))
            return
        end = time.time() + seconds
        while time.time() < end:
            p.stepSimulation(physicsClientId=self._cid())
            time.sleep(min(0.02, max(0.0, end - time.time())))

    def _goto_ee_visible(
        self,
        world: WorldState,
        target: Pose,
        *,
        duration_sec: float = 0.8,
        hold_sec: float = 0.0,
    ) -> None:
        """EE move for wipe/measure. Wall-clock pacing only when --real-time."""
        start = world.robot.ee_pose
        if self.gui and self.real_time:
            frames = max(8, int(duration_sec * 16))
            dt = duration_sec / frames
        elif self.gui:
            frames = max(6, int(duration_sec * 8))
            dt = 0.0
        else:
            frames = max(4, int(duration_sec * 4))
            dt = 0.0
        for i in range(1, frames + 1):
            a = i / frames
            pose = Pose(
                x=start.x + (target.x - start.x) * a,
                y=start.y + (target.y - start.y) * a,
                z=start.z + (target.z - start.z) * a,
                yaw=start.yaw + (target.yaw - start.yaw) * a,
            )
            self._set_ee_pose(pose)
            world.robot.ee_pose = pose
            self._step(1 if dt == 0.0 else 2)
            if dt > 0:
                time.sleep(dt)
        self._set_ee_pose(target)
        world.robot.ee_pose = target
        if hold_sec > 0:
            self._viz_wait(hold_sec)

    def _set_ee_pose(self, pose: Pose) -> None:
        cid = self._cid()
        assert self._ee_body is not None
        orn = p.getQuaternionFromEuler([0, 0, pose.yaw])
        p.resetBasePositionAndOrientation(
            self._ee_body, [pose.x, pose.y, pose.z], orn, physicsClientId=cid
        )
        gap = (
            self._gripper_open_gap
            if (self._world and self._world.robot.gripper == "open")
            else self._gripper_closed_gap
        )
        self._place_fingers(pose, gap)

    def _place_fingers(self, pose: Pose, gap: float) -> None:
        cid = self._cid()
        assert self._finger_l is not None and self._finger_r is not None
        # fingers below palm along -z, separated along y
        z = pose.z - 0.05
        half = max(gap / 2, 0.005)
        orn = p.getQuaternionFromEuler([0, 0, pose.yaw])
        p.resetBasePositionAndOrientation(
            self._finger_l, [pose.x, pose.y - half, z], orn, physicsClientId=cid
        )
        p.resetBasePositionAndOrientation(
            self._finger_r, [pose.x, pose.y + half, z], orn, physicsClientId=cid
        )

    def _set_finger_gap(self, gap: float) -> None:
        if self._world is None:
            return
        self._place_fingers(self._world.robot.ee_pose, gap)

    def _sync_holding_object(self, world: WorldState) -> None:
        if not self._holding_id or self._constraint_id is None:
            return
        # constraint keeps object; sync xyz from body
        body = self._obj_body.get(self._holding_id)
        if body is None:
            return
        pos, _ = p.getBasePositionAndOrientation(body, physicsClientId=self._cid())
        obj = world.objects[self._holding_id]
        obj.xyz = Pose(x=pos[0], y=pos[1], z=pos[2], yaw=obj.xyz.yaw)
        obj.attached_to = "ee"

    def _sync_world(self, world: WorldState) -> None:
        cid = self._cid()
        for oid, body in self._obj_body.items():
            pos, orn = p.getBasePositionAndOrientation(body, physicsClientId=cid)
            yaw = p.getEulerFromQuaternion(orn)[2]
            obj = world.objects[oid]
            obj.xyz = Pose(x=pos[0], y=pos[1], z=pos[2], yaw=yaw)
            if world.robot.holding == oid:
                obj.attached_to = "ee"
            else:
                obj.attached_to = None
        if self._ee_body is not None:
            pos, orn = p.getBasePositionAndOrientation(self._ee_body, physicsClientId=cid)
            yaw = p.getEulerFromQuaternion(orn)[2]
            world.robot.ee_pose = Pose(x=pos[0], y=pos[1], z=pos[2], yaw=yaw)
        world.robot.holding = self._holding_id

    def _move_ee_smooth(self, world: WorldState, target: Pose, steps: int | None = None) -> None:
        steps = steps or self.steps_per_action
        start = world.robot.ee_pose
        # Remember free object poses so approach jitter does not accumulate
        pinned = {
            oid: (obj.xyz.x, obj.xyz.y, obj.xyz.z, obj.xyz.yaw)
            for oid, obj in world.objects.items()
            if oid != self._holding_id
        }
        for i in range(1, steps + 1):
            a = i / steps
            pose = Pose(
                x=start.x + (target.x - start.x) * a,
                y=start.y + (target.y - start.y) * a,
                z=start.z + (target.z - start.z) * a,
                yaw=target.yaw,
            )
            self._set_ee_pose(pose)
            self._step(1)
            world.robot.ee_pose = pose
        self._set_ee_pose(target)
        world.robot.ee_pose = target
        # Re-pin unheld objects (table friction / numerical drift)
        cid = self._cid()
        for oid, (x, y, z, yaw) in pinned.items():
            body = self._obj_body.get(oid)
            if body is None:
                continue
            p.resetBasePositionAndOrientation(
                body, [x, y, z], p.getQuaternionFromEuler([0, 0, yaw]), physicsClientId=cid
            )
            p.resetBaseVelocity(body, [0, 0, 0], [0, 0, 0], physicsClientId=cid)
        self._settle(10)
        self._sync_world(world)

    def _can_grasp(self, world: WorldState, obj: SceneObject) -> bool:
        ee = world.robot.ee_pose
        if not obj.graspable:
            return False
        dist_xy = math.hypot(ee.x - obj.xyz.x, ee.y - obj.xyz.y)
        if dist_xy > world.grasp_xy_tolerance:
            return False
        # Soft compare: include small float slack; thin boxes use center z
        if abs(ee.z - obj.xyz.z) > world.grasp_z_tolerance + 1e-4:
            return False
        return True

    def _attach(self, world: WorldState, oid: str) -> None:
        cid = self._cid()
        assert self._ee_body is not None
        body = self._obj_body[oid]
        self._detach(world)
        # Align object under EE before constraint
        ee = world.robot.ee_pose
        obj = world.objects[oid]
        p.resetBasePositionAndOrientation(
            body,
            [ee.x, ee.y, ee.z - 0.02],
            p.getQuaternionFromEuler([0, 0, obj.xyz.yaw]),
            physicsClientId=cid,
        )
        self._constraint_id = p.createConstraint(
            parentBodyUniqueId=self._ee_body,
            parentLinkIndex=-1,
            childBodyUniqueId=body,
            childLinkIndex=-1,
            jointType=p.JOINT_FIXED,
            jointAxis=[0, 0, 0],
            parentFramePosition=[0, 0, -0.02],
            childFramePosition=[0, 0, 0],
            physicsClientId=cid,
        )
        self._holding_id = oid
        world.robot.holding = oid
        world.objects[oid].attached_to = "ee"

    def _detach(self, world: WorldState) -> None:
        if self._constraint_id is not None:
            try:
                p.removeConstraint(self._constraint_id, physicsClientId=self._cid())
            except Exception:  # noqa: BLE001
                pass
            self._constraint_id = None
        if self._holding_id and self._holding_id in world.objects:
            world.objects[self._holding_id].attached_to = None
        self._holding_id = None
        world.robot.holding = None

    # --- SimBackend API ------------------------------------------------

    def restore_from_world(self, world: WorldState) -> None:
        """Rewind PyBullet bodies to match checkpoint WorldState (for eval retry)."""
        cid = self._cid()
        self._world = world
        # Drop old grasp constraint
        if self._constraint_id is not None:
            try:
                p.removeConstraint(self._constraint_id, physicsClientId=cid)
            except Exception:  # noqa: BLE001
                pass
            self._constraint_id = None
        self._holding_id = None

        for oid, obj in world.objects.items():
            body = self._obj_body.get(oid)
            if body is None:
                continue
            p.resetBasePositionAndOrientation(
                body,
                [obj.xyz.x, obj.xyz.y, obj.xyz.z],
                p.getQuaternionFromEuler([0, 0, obj.xyz.yaw]),
                physicsClientId=cid,
            )
            p.resetBaseVelocity(body, [0, 0, 0], [0, 0, 0], physicsClientId=cid)

        self._set_ee_pose(world.robot.ee_pose)
        gap = (
            self._gripper_open_gap
            if world.robot.gripper == "open"
            else self._gripper_closed_gap
        )
        self._set_finger_gap(gap)

        if world.robot.holding and world.robot.holding in self._obj_body:
            self._attach(world, world.robot.holding)
        else:
            world.robot.holding = None
            self._holding_id = None

        self._settle(15)
        self._sync_world(world)

    def apply(self, action: str, args: dict, world: WorldState) -> ActResult:
        self._world = world
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

    def _list_objects(self, world: WorldState, args: dict) -> ActResult:
        self._sync_world(world)
        items = [
            {"id": o.id, "name": o.display_name, "x": o.xyz.x, "y": o.xyz.y, "z": o.xyz.z}
            for o in world.objects.values()
        ]
        return ActResult(ok=True, action="list_objects", message=f"{len(items)} objects", observation={"objects": items})

    def _get_object_pose(self, world: WorldState, args: dict) -> ActResult:
        self._sync_world(world)
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
        self._sync_world(world)
        oid = args.get("object_id")
        if not oid or oid not in world.objects:
            return ActResult(ok=False, action="move_above", message="object_not_found")
        obj = world.objects[oid]
        z_offset = float(args.get("z_offset", world.motion_default_z_offset))
        target_z = obj.xyz.z + obj.height / 2 + z_offset
        target = Pose(x=obj.xyz.x, y=obj.xyz.y, z=target_z, yaw=0.0)
        self._move_ee_smooth(world, target)
        return ActResult(
            ok=True,
            action="move_above",
            message=f"ee moved above {oid}",
            observation={"ee": world.robot.ee_pose.model_dump()},
        )

    def _move_down(self, world: WorldState, args: dict) -> ActResult:
        self._sync_world(world)
        delta_z = float(args.get("delta_z", 0.08))
        ee = world.robot.ee_pose
        # Allow descending near thin table objects (rag/ruler ~z=0.01)
        new_z = max(world.table_z + 0.02, ee.z - delta_z)
        target = Pose(x=ee.x, y=ee.y, z=new_z, yaw=ee.yaw)
        self._move_ee_smooth(world, target)
        return ActResult(
            ok=True,
            action="move_down",
            message=f"ee lowered by {delta_z}",
            observation={"ee": world.robot.ee_pose.model_dump()},
        )

    def _close_gripper(self, world: WorldState, args: dict) -> ActResult:
        self._sync_world(world)
        if world.robot.gripper == "closed" and world.robot.holding:
            return ActResult(
                ok=True,
                action="close_gripper",
                message="already_holding",
                observation={"holding": world.robot.holding},
            )
        world.robot.gripper = "closed"
        self._set_finger_gap(self._gripper_closed_gap)
        self._settle(30)

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
            if self._can_grasp(world, obj):
                dist = math.hypot(ee.x - obj.xyz.x, ee.y - obj.xyz.y)
                candidates.append((dist, obj))
        if not candidates:
            self._sync_world(world)
            return ActResult(
                ok=False,
                action="close_gripper",
                message="grasp_miss",
                observation={"holding": None},
            )
        candidates.sort(key=lambda t: t[0])
        chosen = candidates[0][1]
        self._attach(world, chosen.id)
        self._settle(20)
        self._sync_world(world)
        return ActResult(
            ok=True,
            action="close_gripper",
            message=f"grasped_{chosen.id}",
            observation={"holding": chosen.id},
        )

    def _open_gripper(self, world: WorldState, args: dict) -> ActResult:
        self._sync_world(world)
        held = world.robot.holding
        self._detach(world)
        world.robot.gripper = "open"
        self._set_finger_gap(self._gripper_open_gap)
        self._settle(60)  # let object fall/settle on table
        self._sync_world(world)
        msg = f"released_{held}" if held else "opened"
        return ActResult(ok=True, action="open_gripper", message=msg, observation={"holding": None})

    def _lift(self, world: WorldState, args: dict) -> ActResult:
        self._sync_world(world)
        delta_z = float(args.get("delta_z", 0.12))
        ee = world.robot.ee_pose
        target = Pose(x=ee.x, y=ee.y, z=ee.z + delta_z, yaw=ee.yaw)
        self._move_ee_smooth(world, target)
        return ActResult(
            ok=True,
            action="lift",
            message=f"lifted by {delta_z}",
            observation={"ee": world.robot.ee_pose.model_dump(), "holding": world.robot.holding},
        )

    def _release_to_pose(self, world: WorldState, held: str) -> None:
        if self._constraint_id is not None:
            try:
                p.removeConstraint(self._constraint_id, physicsClientId=self._cid())
            except Exception:  # noqa: BLE001
                pass
            self._constraint_id = None
        self._holding_id = None
        if held and held in self._obj_body:
            obj = world.objects[held]
            p.resetBasePositionAndOrientation(
                self._obj_body[held],
                [obj.xyz.x, obj.xyz.y, obj.xyz.z],
                p.getQuaternionFromEuler([0, 0, obj.xyz.yaw]),
                physicsClientId=self._cid(),
            )
            p.resetBaseVelocity(
                self._obj_body[held], [0, 0, 0], [0, 0, 0], physicsClientId=self._cid()
            )
        world.robot.gripper = "open"
        self._set_finger_gap(self._gripper_open_gap)
        self._settle(40)
        self._sync_world(world)

    def _place_down(self, world: WorldState, args: dict) -> ActResult:
        self._sync_world(world)
        held = world.robot.holding
        result = sim_coupling_ops.place_down(world, args)
        if not result.ok:
            return result
        self._release_to_pose(world, held or "")
        return result

    def _place_home(self, world: WorldState, args: dict) -> ActResult:
        self._sync_world(world)
        held = world.robot.holding
        result = sim_coupling_ops.place_home(world, args)
        if not result.ok:
            return result
        self._release_to_pose(world, held or "")
        return result

    def _move_to(self, world: WorldState, args: dict) -> ActResult:
        self._sync_world(world)
        ee = world.robot.ee_pose
        target = Pose(
            x=float(args.get("x", ee.x)),
            y=float(args.get("y", ee.y)),
            z=float(args.get("z", ee.z)),
            yaw=float(args.get("yaw", ee.yaw)),
        )
        self._move_ee_smooth(world, target)
        return ActResult(
            ok=True,
            action="move_to",
            message=f"ee_to_({target.x:.2f},{target.y:.2f},{target.z:.2f})",
            observation={"ee": world.robot.ee_pose.model_dump()},
        )

    def _return_home(self, world: WorldState, args: dict) -> ActResult:
        self._sync_world(world)
        if world.home_ee is None:
            return ActResult(ok=False, action="return_home", message="no_home_ee")
        self._move_ee_smooth(world, world.home_ee)
        result = sim_coupling_ops.return_home(world, args)
        self._set_ee_pose(world.robot.ee_pose)
        if world.robot.holding is None:
            self._set_finger_gap(self._gripper_open_gap)
        self._settle(20)
        self._sync_world(world)
        return result

    def _wipe_inner(self, world: WorldState, args: dict) -> ActResult:
        self._sync_world(world)
        result = sim_coupling_ops.wipe_inner(world, args)
        if not result.ok:
            return result
        # Scrub motion; long wall-clock only with --real-time
        cid = sim_coupling_ops.active_coupling_id(world)
        coupling = world.objects.get(cid) if cid else None
        if coupling is not None:
            if self.gui:
                print(f"  … wiping {coupling.display_name}: dip + scrub")
            start = world.robot.ee_pose
            cx, cy = coupling.xyz.x, coupling.xyz.y
            wipe_z = max(world.table_z + 0.05, coupling.xyz.z + 0.02)
            slow = self.gui and self.real_time
            self._goto_ee_visible(
                world,
                Pose(x=cx, y=cy, z=wipe_z, yaw=start.yaw),
                duration_sec=0.9 if slow else 0.25,
                hold_sec=0.25 if slow else 0.0,
            )
            amp = 0.045
            path = [
                Pose(x=cx - amp, y=cy, z=wipe_z, yaw=start.yaw),
                Pose(x=cx + amp, y=cy, z=wipe_z, yaw=start.yaw),
                Pose(x=cx, y=cy - amp, z=wipe_z, yaw=start.yaw),
                Pose(x=cx, y=cy + amp, z=wipe_z, yaw=start.yaw),
                Pose(x=cx, y=cy, z=wipe_z, yaw=start.yaw),
            ]
            if not slow:
                path = path[::2]  # fewer strokes when not real-time
            for pose in path:
                self._goto_ee_visible(
                    world, pose, duration_sec=0.4 if slow else 0.12
                )
            self._goto_ee_visible(
                world,
                Pose(x=cx, y=cy, z=start.z, yaw=start.yaw),
                duration_sec=0.7 if slow else 0.2,
                hold_sec=0.15 if slow else 0.0,
            )
        self._settle(10)
        self._sync_world(world)
        return result

    def _measure_inner(self, world: WorldState, args: dict) -> ActResult:
        self._sync_world(world)
        result = sim_coupling_ops.measure_inner(world, args)
        if not result.ok:
            return result
        # Slow dip-hold-rise so measuring is obvious in the GUI
        cid = sim_coupling_ops.active_coupling_id(world)
        coupling = world.objects.get(cid) if cid else None
        ee = world.robot.ee_pose
        if self.gui:
            name = coupling.display_name if coupling else "coupling"
            print(f"  … measuring {name}: dip into bore, hold, rise")
        slow = self.gui and self.real_time
        if coupling is not None:
            mid_z = max(world.table_z + 0.05, coupling.xyz.z + 0.02)
            down = Pose(
                x=coupling.xyz.x, y=coupling.xyz.y, z=mid_z, yaw=ee.yaw
            )
            self._goto_ee_visible(
                world, down, duration_sec=1.0 if slow else 0.25, hold_sec=0.5 if slow else 0.0
            )
            if slow:
                wiggle = 0.02
                self._goto_ee_visible(
                    world,
                    Pose(x=down.x - wiggle, y=down.y, z=mid_z, yaw=ee.yaw),
                    duration_sec=0.3,
                )
                self._goto_ee_visible(
                    world,
                    Pose(x=down.x + wiggle, y=down.y, z=mid_z, yaw=ee.yaw),
                    duration_sec=0.3,
                )
                self._goto_ee_visible(world, down, duration_sec=0.25, hold_sec=0.25)
            self._goto_ee_visible(
                world, ee, duration_sec=0.9 if slow else 0.2, hold_sec=0.15 if slow else 0.0
            )
        else:
            down = Pose(
                x=ee.x, y=ee.y, z=max(world.table_z + 0.08, ee.z - 0.08), yaw=ee.yaw
            )
            self._goto_ee_visible(
                world, down, duration_sec=0.9 if slow else 0.2, hold_sec=0.4 if slow else 0.0
            )
            self._goto_ee_visible(world, ee, duration_sec=0.9 if slow else 0.2)
        self._sync_world(world)
        return result

    def _done(self, world: WorldState, args: dict) -> ActResult:
        self._sync_world(world)
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
