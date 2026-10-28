from pathlib import Path

import yaml

from actforge.adapters.sim_mock import MockSim
from actforge.util.config import load_scene

ROOT = Path(__file__).resolve().parents[1]


def test_mock_sim_reset_from_cfg():
    cfg = yaml.safe_load((ROOT / "configs" / "scene_desk_v1.yaml").read_text(encoding="utf-8"))
    sim = MockSim()
    world = sim.reset(cfg)
    assert "can_cola" in world.objects
    r = sim.apply("list_objects", {}, world)
    assert r.ok


def test_mock_sim_reset_from_world_copy():
    world = load_scene(ROOT / "configs" / "scene_desk_v1.yaml")
    sim = MockSim()
    copy = sim.reset(world)
    copy.robot.holding = "can_cola"
    assert world.robot.holding is None
