import pytest

from actforge.adapters.sim_pybullet import HAS_PYBULLET, PyBulletSim
from actforge.util.config import load_scene
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(not HAS_PYBULLET, reason="pybullet not installed")


def test_pybullet_grasp_and_lift():
    world = load_scene(ROOT / "configs" / "scene_desk_v1.yaml")
    sim = PyBulletSim(gui=False)
    try:
        world = sim.reset(world)
        r1 = sim.apply("move_above", {"object_id": "can_cola", "z_offset": 0.12}, world)
        assert r1.ok
        r2 = sim.apply("move_down", {"delta_z": 0.16}, world)
        assert r2.ok
        r3 = sim.apply("close_gripper", {}, world)
        assert r3.ok, r3.message
        assert world.robot.holding == "can_cola"
        z_before = world.objects["can_cola"].xyz.z
        r4 = sim.apply("lift", {"delta_z": 0.12}, world)
        assert r4.ok
        assert world.objects["can_cola"].xyz.z > z_before + 0.05
    finally:
        sim.close()


def test_pybullet_grasp_miss():
    world = load_scene(ROOT / "configs" / "scene_desk_v1.yaml")
    sim = PyBulletSim(gui=False)
    try:
        world = sim.reset(world)
        # move EE far away then close
        from actforge.worldview.models import Pose

        world.robot.ee_pose = Pose(x=0.4, y=0.4, z=0.2, yaw=0.0)
        # sync kinematic body
        sim._set_ee_pose(world.robot.ee_pose)
        r = sim.apply("close_gripper", {}, world)
        assert not r.ok
        assert r.message == "grasp_miss"
    finally:
        sim.close()
