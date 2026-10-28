from actforge.worldview.models import VerifyResult, WorldState


class CouplingCleanVerifier:
    def __init__(
        self,
        require_wiped: bool = True,
        require_measured: bool = True,
        require_empty_hand: bool = True,
        require_returned_home: bool = True,
    ):
        self.require_wiped = require_wiped
        self.require_measured = require_measured
        self.require_empty_hand = require_empty_hand
        self.require_returned_home = require_returned_home

    def check(self, world: WorldState) -> VerifyResult:
        flags = world.task_flags or {}
        wiped = bool(flags.get("coupling_wiped"))
        measured = bool(flags.get("coupling_measured"))
        returned = bool(flags.get("returned_home"))
        holding = world.robot.holding
        metrics = {
            "coupling_wiped": wiped,
            "coupling_measured": measured,
            "inner_diameter_mm": flags.get("inner_diameter_mm"),
            "holding": holding,
            "returned_home": returned,
        }
        if self.require_wiped and not wiped:
            return VerifyResult(success=False, reason="not_wiped", metrics=metrics)
        if self.require_measured and not measured:
            return VerifyResult(success=False, reason="not_measured", metrics=metrics)
        if self.require_empty_hand and holding is not None:
            return VerifyResult(success=False, reason="hand_not_empty", metrics=metrics)
        if self.require_returned_home and not returned:
            return VerifyResult(success=False, reason="not_returned_home", metrics=metrics)
        return VerifyResult(success=True, reason="wiped_measured_home", metrics=metrics)
