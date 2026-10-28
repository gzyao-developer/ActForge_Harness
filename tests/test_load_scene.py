from pathlib import Path

from actforge.util.config import load_scene

ROOT = Path(__file__).resolve().parents[1]


def test_load_scene_has_can_and_cup():
    world = load_scene(ROOT / "configs" / "scene_desk_v1.yaml")
    assert world.scene_id == "desk_v1"
    assert "can_cola" in world.objects
    assert "cup_white" in world.objects
    assert world.objects["can_cola"].display_name == "易拉罐"
    assert world.robot.gripper == "open"
    assert world.robot.holding is None
