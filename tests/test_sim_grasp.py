from pathlib import Path

from actforge.adapters.sim_mock import MockSim
from actforge.util.config import load_scene
from actforge.worldview.models import Pose

ROOT = Path(__file__).resolve().parents[1]


def test_sim_grasp_success():
    world = load_scene(ROOT / "configs" / "scene_desk_v1.yaml")
    sim = MockSim()
    r1 = sim.apply("move_above", {"object_id": "can_cola", "z_offset": 0.12}, world)
    assert r1.ok
    r2 = sim.apply("move_down", {"delta_z": 0.16}, world)
    assert r2.ok
    r3 = sim.apply("close_gripper", {}, world)
    assert r3.ok, r3.message
    assert world.robot.holding == "can_cola"
    r4 = sim.apply("lift", {"delta_z": 0.12}, world)
    assert r4.ok
    assert world.objects["can_cola"].xyz.z >= world.table_z + 0.10


def test_grasp_miss():
    world = load_scene(ROOT / "configs" / "scene_desk_v1.yaml")
    sim = MockSim()
    # deliberately offset EE away from can
    world.robot.ee_pose = Pose(x=0.40, y=0.40, z=0.06, yaw=0.0)
    r = sim.apply("close_gripper", {}, world)
    assert not r.ok
    assert r.message == "grasp_miss"
    assert world.robot.holding is None
