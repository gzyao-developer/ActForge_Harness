from __future__ import annotations

from typing import Any

from actforge.adapters.sim_mock import MockSim


def create_sim(backend: str = "mock", *, gui: bool = False, real_time: bool = False) -> Any:
    """Create a SimBackend by name: mock | pybullet."""
    name = (backend or "mock").lower().strip()
    if name in ("mock", "mocksim"):
        return MockSim()
    if name in ("pybullet", "bullet", "pb"):
        from actforge.adapters.sim_pybullet import PyBulletSim

        return PyBulletSim(gui=gui, real_time=real_time and gui)
    raise ValueError(f"Unknown sim backend: {backend}. Use mock|pybullet")
