from pathlib import Path

from actforge.adapters.sim_mock import MockSim
from actforge.util.config import load_scene
from actforge.verify.pick_can import PickCanVerifier

ROOT = Path(__file__).resolve().parents[1]


def test_verify_success_path():
    world = load_scene(ROOT / "configs" / "scene_desk_v1.yaml")
    sim = MockSim()
    sim.apply("move_above", {"object_id": "can_cola", "z_offset": 0.12}, world)
    sim.apply("move_down", {"delta_z": 0.16}, world)
    sim.apply("close_gripper", {}, world)
    sim.apply("lift", {"delta_z": 0.12}, world)
    sim.apply("return_home", {}, world)
    v = PickCanVerifier("can_cola", min_lift_z=0.10, table_z=world.table_z)
    result = v.check(world)
    assert result.success
    assert result.reason == "picked_lifted_home"


def test_verify_early_done_fails():
    world = load_scene(ROOT / "configs" / "scene_desk_v1.yaml")
    v = PickCanVerifier("can_cola", min_lift_z=0.10, table_z=world.table_z)
    result = v.check(world)
    assert not result.success
    assert result.reason == "not_holding"
