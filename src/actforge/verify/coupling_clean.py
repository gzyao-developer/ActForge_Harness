from actforge.worldview.models import VerifyResult, WorldState


class CouplingCleanVerifier:
    """验收：流程归档完成（与质量合格/不合格解耦）。"""

    def __init__(
        self,
        require_wiped: bool = True,
        require_measured: bool = True,
        require_empty_hand: bool = True,
        require_returned_home: bool = True,
        expected_workpieces: list[str] | None = None,
    ):
        self.require_wiped = require_wiped
        self.require_measured = require_measured
        self.require_empty_hand = require_empty_hand
        self.require_returned_home = require_returned_home
        self.expected_workpieces = expected_workpieces or ["A", "B"]

    def check(self, world: WorldState) -> VerifyResult:
        flags = world.task_flags or {}
        archived = list(flags.get("archived_workpieces") or [])
        results = dict(flags.get("workpiece_results") or {})
        returned = bool(flags.get("returned_home"))
        holding = world.robot.holding
        metrics = {
            "archived_workpieces": archived,
            "workpiece_results": results,
            "holding": holding,
            "returned_home": returned,
            "inspection_events": len(flags.get("inspection_log") or []),
        }

        # Prefer pipeline completion (表2：不合格也归档完成)
        if self.expected_workpieces:
            missing = [wp for wp in self.expected_workpieces if wp not in archived]
            if missing:
                return VerifyResult(
                    success=False,
                    reason=f"not_archived:{','.join(missing)}",
                    metrics=metrics,
                )
            if self.require_empty_hand and holding is not None:
                return VerifyResult(success=False, reason="hand_not_empty", metrics=metrics)
            if self.require_returned_home and not returned:
                return VerifyResult(success=False, reason="not_returned_home", metrics=metrics)
            return VerifyResult(
                success=True,
                reason="inspection_pipeline_complete",
                metrics=metrics,
            )

        # Legacy single-piece fallback
        wiped = bool(flags.get("coupling_wiped"))
        measured = bool(flags.get("coupling_measured"))
        metrics.update(
            {
                "coupling_wiped": wiped,
                "coupling_measured": measured,
                "inner_diameter_mm": flags.get("inner_diameter_mm"),
            }
        )
        if self.require_wiped and not wiped:
            return VerifyResult(success=False, reason="not_wiped", metrics=metrics)
        if self.require_measured and not measured:
            return VerifyResult(success=False, reason="not_measured", metrics=metrics)
        if self.require_empty_hand and holding is not None:
            return VerifyResult(success=False, reason="hand_not_empty", metrics=metrics)
        if self.require_returned_home and not returned:
            return VerifyResult(success=False, reason="not_returned_home", metrics=metrics)
        return VerifyResult(success=True, reason="wiped_measured_home", metrics=metrics)
