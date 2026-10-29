from pathlib import Path

from actforge.inspection.guide import inspection_progress
from actforge.util.config import load_scene

ROOT = Path(__file__).resolve().parents[1]


def test_inspection_guide_starts_with_admit_a():
    world = load_scene(ROOT / "configs" / "scene_coupling_v1.yaml")
    prog = inspection_progress(world)
    assert prog["recommended_action"] == "task_admit"
    assert prog["recommended_args"]["workpiece"] == "A"
    assert prog["recommended_args"]["object_id"] == "coupling_A"


def test_inspection_guide_after_admit_wants_wipe():
    world = load_scene(ROOT / "configs" / "scene_coupling_v1.yaml")
    world.task_flags.update(
        {
            "current_workpiece": "A",
            "current_coupling_id": "coupling_A",
            "measure_allowed": False,
        }
    )
    prog = inspection_progress(world)
    assert prog["phase"] == "wipe"
    assert prog["recommended_action"] == "move_above"
    assert prog["recommended_args"]["object_id"] == "rag"
