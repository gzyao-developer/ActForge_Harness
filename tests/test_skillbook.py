from pathlib import Path

from actforge.skillbook.catalog import Skillbook, scan_skills

ROOT = Path(__file__).resolve().parents[1]


def test_catalog_loads_pick_can():
    catalog = scan_skills(ROOT / "skills")
    assert any(s.name == "pick-can" for s in catalog)
    assert any(s.name == "grasp-retry" for s in catalog)


def test_load_skill_sets_active():
    skillbook = Skillbook(ROOT / "skills")
    result = skillbook.load("pick-can")
    assert result.ok
    assert skillbook.active is not None
    assert "move_above" in skillbook.active.body


def test_load_unknown_skill():
    skillbook = Skillbook(ROOT / "skills")
    result = skillbook.load("no-such")
    assert not result.ok
    assert result.message == "unknown_skill"
