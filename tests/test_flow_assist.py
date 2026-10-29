from actforge.inspection.assist import CouplingFlowAssist
from actforge.worldview.models import (
    ActionIntent,
    ActResult,
    Pose,
    RobotState,
    SceneObject,
    WorldState,
)


def _world(**flags) -> WorldState:
    return WorldState(
        scene_id="test",
        table_z=0.0,
        robot=RobotState(ee_pose=Pose(x=0, y=0, z=0.2), gripper="open", holding=None),
        objects={
            "rag": SceneObject(
                id="rag",
                label="rag",
                display_name="抹布",
                xyz=Pose(x=0.3, y=0.1, z=0.02),
            ),
            "coupling_A": SceneObject(
                id="coupling_A",
                label="coupling",
                display_name="接箍A",
                xyz=Pose(x=0.4, y=0.0, z=0.05),
            ),
        },
        object_homes={"rag": Pose(x=0.3, y=0.1, z=0.02)},
        task_flags=dict(flags),
        coupling_cfg={"workpieces": {"A": {"object_id": "coupling_A"}}},
    )


def test_assist_forces_wipe_return_when_rag_put_back():
    world = _world(coupling_wiped=True, current_workpiece="A", current_coupling_id="coupling_A")
    assist = CouplingFlowAssist()
    assist.bind_world(world)
    intent = ActionIntent(action="move_above", args={"object_id": "ruler", "z_offset": 0.1})
    out = assist.override_decide(intent, world)
    assert out.action == "wipe_return"


def test_assist_forces_put_rag_when_holding_after_wipe():
    world = _world(coupling_wiped=True)
    world.robot.holding = "rag"
    assist = CouplingFlowAssist()
    assist.bind_world(world)
    intent = ActionIntent(action="wipe_return", args={})
    out = assist.override_decide(intent, world)
    assert out.action == "move_to"
    assert "x" in out.args


def test_assist_followup_wipe_return_after_place_home():
    world = _world(coupling_wiped=True)
    assist = CouplingFlowAssist()
    assist.bind_world(world)
    fus = assist.followups_after(
        ActionIntent(action="place_home", args={}),
        ActResult(ok=True, action="place_home", message="placed"),
        world,
    )
    assert len(fus) == 1
    assert fus[0].action == "wipe_return"


def test_assist_breaks_repeat_loop():
    world = _world(
        coupling_wiped=True,
        cleaning_status="pending_review",
        current_workpiece="A",
        current_coupling_id="coupling_A",
    )
    assist = CouplingFlowAssist(max_same=2)
    assist.bind_world(world)
    intent = ActionIntent(action="note_write", args={"text": "x"})
    ok = ActResult(ok=True, action="note_write", message="ok")
    assist.record_executed(intent, ok)
    assist.record_executed(intent, ok)
    out = assist.override_decide(intent, world)
    assert out.action != "note_write"
