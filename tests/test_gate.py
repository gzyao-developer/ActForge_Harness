from pathlib import Path

from actforge.policy_gate.rules import check
from actforge.util.config import load_scene
from actforge.worldview.models import ActionIntent

ROOT = Path(__file__).resolve().parents[1]


def test_unknown_action_rejected():
    world = load_scene(ROOT / "configs" / "scene_desk_v1.yaml")
    result = check(ActionIntent(action="fly_away", args={}), world)
    assert not result.allowed
    assert "unknown_action" in result.reason


def test_bad_object_id_rejected():
    world = load_scene(ROOT / "configs" / "scene_desk_v1.yaml")
    result = check(
        ActionIntent(action="move_above", args={"object_id": "not_exist"}),
        world,
    )
    assert not result.allowed
    assert "object_not_found" in result.reason


def test_close_while_holding_rejected():
    world = load_scene(ROOT / "configs" / "scene_desk_v1.yaml")
    world.robot.holding = "can_cola"
    result = check(ActionIntent(action="close_gripper", args={}), world)
    assert not result.allowed
    assert result.reason == "already_holding"


def test_lift_without_holding_allowed_with_warning():
    world = load_scene(ROOT / "configs" / "scene_desk_v1.yaml")
    result = check(ActionIntent(action="lift", args={"delta_z": 0.1}), world)
    assert result.allowed
    assert result.reason == "warn_lift_without_holding"
