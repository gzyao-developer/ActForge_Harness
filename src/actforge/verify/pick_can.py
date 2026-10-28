from actforge.worldview.models import VerifyResult, WorldState


class PickCanVerifier:
    def __init__(
        self,
        object_id: str,
        min_lift_z: float,
        table_z: float = 0.0,
        require_returned_home: bool = True,
    ):
        self.object_id = object_id
        self.min_lift_z = min_lift_z
        self.table_z = table_z
        self.require_returned_home = require_returned_home

    def check(self, world: WorldState) -> VerifyResult:
        need_z = self.table_z + self.min_lift_z
        holding = world.robot.holding
        gripper = world.robot.gripper
        obj = world.objects.get(self.object_id)
        can_z = obj.xyz.z if obj else None
        returned = bool((world.task_flags or {}).get("returned_home"))

        metrics = {
            "holding": holding,
            "gripper": gripper,
            "can_z": can_z,
            "need_z": need_z,
            "returned_home": returned,
        }

        if holding != self.object_id:
            return VerifyResult(success=False, reason="not_holding", metrics=metrics)
        if gripper != "closed":
            return VerifyResult(success=False, reason="gripper_not_closed", metrics=metrics)
        if obj is None:
            return VerifyResult(success=False, reason="object_missing", metrics=metrics)
        if obj.xyz.z < need_z:
            return VerifyResult(success=False, reason="not_lifted_enough", metrics=metrics)
        if self.require_returned_home and not returned:
            return VerifyResult(success=False, reason="not_returned_home", metrics=metrics)
        return VerifyResult(success=True, reason="picked_lifted_home", metrics=metrics)
