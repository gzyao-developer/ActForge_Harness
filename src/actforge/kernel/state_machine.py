from __future__ import annotations

import time
from typing import Any, Optional, Protocol

from actforge.adapters.llm_openai import LLMPolicyError
from actforge.evaluate.models import EvaluateResult
from actforge.evaluate.step_eval import StepEvaluator
from actforge.inspection.assist import CouplingFlowAssist
from actforge.kernel import events
from actforge.policy_gate.rules import Gate
from actforge.recall.service import RecallService, TaskOutcome
from actforge.skillbook.catalog import Skillbook
from actforge.util.logging_jsonl import EventLog
from actforge.util.process_log import ProcessLog, format_inspection_line
from actforge.worldview.models import ActionIntent, ActResult, WorldState
from actforge.worldview.snapshot import Snapshot, build_snapshot


class Policy(Protocol):
    def decide(self, snap: Snapshot) -> ActionIntent: ...


def run_task(
    instruction: str,
    world: WorldState,
    policy: Policy,
    gate: Gate,
    registry: Any,
    verifier: Any,
    limits: dict[str, Any],
    skillbook: Skillbook,
    recall: RecallService,
    event_log: EventLog,
    goal_object_id: str,
    *,
    print_step: bool = True,
    verbose: bool = False,
    require_load_skill: bool = False,
    max_same_fail: int = 6,
    evaluator: StepEvaluator | None = None,
    evaluate_cfg: dict[str, Any] | None = None,
    sim: Any | None = None,
    process_log: ProcessLog | None = None,
) -> TaskOutcome:
    """
    Control loop:

      SENSE → DECIDE → GATE → ACT → EVALUATE
        → score < threshold: rewind world/GUI to pre-ACT, redo current action
        → score >= threshold: VERIFY → next step
    """
    max_steps = int(limits.get("max_steps", 24))
    timeout_sec = float(limits.get("timeout_sec", 120))
    started = time.monotonic()
    skill_loaded = False
    same_fail_key: str | None = None
    same_fail_count = 0

    eval_cfg = evaluate_cfg or {"enabled": False}
    eval_enabled = bool(eval_cfg.get("enabled", False)) and evaluator is not None
    eval_max_retries = int(eval_cfg.get("max_retries", 2))
    eval_on_exhausted = str(eval_cfg.get("on_exhausted", "continue"))
    apply_suggestions = bool(eval_cfg.get("apply_suggestions", True))
    rewind_on_retry = bool(eval_cfg.get("rewind_on_retry", True))
    rewind_pause_sec = float(eval_cfg.get("rewind_pause_sec", 0.0))

    event_log.emit(events.TASK_STARTED, {"instruction": instruction, "goal": goal_object_id})
    skillbook.reset_active()
    recall.on_task_start(instruction, goal_object_id)
    last_result: ActResult | None = None
    last_evaluation: Optional[dict[str, Any]] = None
    flow_assist = CouplingFlowAssist()
    flow_assist.bind_world(world)

    try:
        for step in range(1, max_steps + 1):
            if time.monotonic() - started > timeout_sec:
                outcome = TaskOutcome(status="timeout", steps=step - 1, reason="timeout")
                recall.on_task_end(outcome, instruction, goal_object_id)
                event_log.emit(events.TASK_FINISHED, {"status": "timeout", "steps": step - 1})
                return outcome

            snap = build_snapshot(
                instruction,
                world,
                step,
                max_steps,
                last_result,
                skillbook=skillbook,
                recall=recall.build_recall_snapshot(),
                goal_object_id=goal_object_id,
                last_evaluation=last_evaluation,
            )
            event_log.emit(events.SENSE_DONE, {"step": step, "snapshot": snap.to_compact_dict()})
            if verbose and print_step:
                active = snap.active_skill["name"] if snap.active_skill else None
                print(
                    f"[step {step}] SENSE holding={world.robot.holding} "
                    f"active_skill={active} notes={len(snap.recall.get('task_notes', []))}"
                )

            try:
                intent = policy.decide(snap)
            except LLMPolicyError as e:
                outcome = TaskOutcome(
                    status="failed",
                    steps=step - 1,
                    reason=e.reason,
                    metrics={"detail": e.detail},
                )
                recall.on_task_end(outcome, instruction, goal_object_id)
                event_log.emit(
                    events.TASK_FINISHED,
                    {"status": "failed", "reason": e.reason, "detail": e.detail},
                )
                return outcome
            except KeyboardInterrupt:
                outcome = TaskOutcome(status="failed", steps=step - 1, reason="user_abort")
                recall.on_task_end(outcome, instruction, goal_object_id)
                event_log.emit(events.TASK_FINISHED, {"status": "failed", "reason": "user_abort"})
                return outcome

            intent = flow_assist.override_decide(intent, world)

            event_log.emit(events.DECIDE_DONE, {"step": step, "intent": intent.model_dump()})
            if print_step:
                args_hint = ""
                if intent.args.get("object_id"):
                    args_hint = f" {intent.args['object_id']}"
                elif intent.args.get("skill_name"):
                    args_hint = f" {intent.args['skill_name']}"
                print(f"[step {step}] DECIDE {intent.action}{args_hint}")

            gate_result = gate.check(intent, world, skillbook=skillbook)
            event_log.emit(events.GATE_CHECKED, {"step": step, **gate_result.model_dump()})
            if print_step:
                print(
                    f"[step {step}] GATE "
                    f"{'allow' if gate_result.allowed else 'deny'} {gate_result.reason}"
                )

            if not gate_result.allowed:
                last_result = ActResult(
                    ok=False, action=intent.action, message=gate_result.reason
                )
                last_evaluation = None
                recall.record_lesson(step, last_result, intent.args)
                fail_key = f"gate:{intent.action}:{gate_result.reason}"
                same_fail_key, same_fail_count = _bump_fail(
                    same_fail_key, same_fail_count, fail_key
                )
                if same_fail_count >= max_same_fail:
                    return _finish_failed(
                        recall,
                        event_log,
                        instruction,
                        goal_object_id,
                        step,
                        "repeated_failure",
                        {"fail_key": fail_key, "count": same_fail_count},
                    )
                continue

            # ACT → EVALUATE → maybe redo current action
            eval_result: EvaluateResult | None = None
            attempts = 1 + (eval_max_retries if eval_enabled else 0)
            for attempt in range(1, attempts + 1):
                world_before = world.model_copy(deep=True)
                act_result = registry.execute(
                    intent.action,
                    world,
                    intent.args,
                    ctx={"skillbook": skillbook, "recall": recall},
                )
                event_log.emit(
                    events.ACT_DONE,
                    {"step": step, "attempt": attempt, **act_result.model_dump()},
                )
                if intent.action == "load_skill" and act_result.ok:
                    skill_loaded = True
                    event_log.emit(
                        events.SKILL_LOADED,
                        {"name": intent.args.get("skill_name") or intent.args.get("name")},
                    )
                last_result = act_result
                recall.record_lesson(step, act_result, intent.args)

                insp = (act_result.observation or {}).get("inspection_event")
                if insp:
                    event_log.emit(events.INSPECTION_EVENT, dict(insp))
                    if process_log is not None:
                        process_log.line(format_inspection_line(insp))

                if print_step:
                    ee = world.robot.ee_pose
                    print(
                        f"[step {step}] ACT{'#'+str(attempt) if attempt > 1 else ''} "
                        f"{'ok' if act_result.ok else 'fail'} "
                        f"{act_result.message} ee=({ee.x:.2f},{ee.y:.2f},{ee.z:.2f})"
                    )

                if not eval_enabled or evaluator is None:
                    if process_log is not None:
                        _log_act_to_process(process_log, intent.action, act_result)
                    break

                eval_result = evaluator.evaluate(
                    intent,
                    act_result,
                    world,
                    world_before=world_before,
                    attempt=attempt,
                )
                last_evaluation = eval_result.to_snapshot_dict()
                event_log.emit(
                    events.EVALUATE_DONE,
                    {"step": step, **last_evaluation},
                )
                if print_step:
                    mark = "PASS" if eval_result.passed else "RETRY"
                    print(
                        f"[step {step}] EVAL {mark} score={eval_result.score:.2f}/"
                        f"{eval_result.threshold:.2f} {eval_result.feedback}"
                    )

                if eval_result.passed:
                    same_fail_key, same_fail_count = None, 0
                    # 只在评估通过后写流程日志，避免重试刷屏
                    if process_log is not None:
                        _log_act_to_process(process_log, intent.action, act_result)
                    break

                # grasp_miss: identical close_gripper retries won't help; hand back to DECIDE
                if (
                    intent.action == "close_gripper"
                    and act_result.message == "grasp_miss"
                ):
                    if process_log is not None:
                        _log_act_to_process(process_log, intent.action, act_result)
                    if rewind_on_retry:
                        _restore_world_inplace(world, world_before)
                        if sim is not None and hasattr(sim, "restore_from_world"):
                            sim.restore_from_world(world)
                    if print_step:
                        print(
                            f"[step {step}] EVAL grasp_miss → handoff to DECIDE "
                            f"(lower more before close)"
                        )
                    break

                # Below threshold → rewind then redo current action
                if attempt < attempts:
                    event_log.emit(
                        events.STEP_RETRY,
                        {
                            "step": step,
                            "action": intent.action,
                            "attempt": attempt,
                            "score": eval_result.score,
                            "suggestions": eval_result.suggestions,
                            "rewind": rewind_on_retry,
                        },
                    )
                    if print_step:
                        print(
                            f"[step {step}] RETRY action={intent.action} "
                            f"because score={eval_result.score:.2f} < {eval_result.threshold:.2f}"
                            + (" (rewind scene)" if rewind_on_retry else "")
                        )
                    if rewind_on_retry:
                        _restore_world_inplace(world, world_before)
                        if sim is not None and hasattr(sim, "restore_from_world"):
                            sim.restore_from_world(world)
                        if rewind_pause_sec > 0:
                            time.sleep(rewind_pause_sec)
                    if apply_suggestions and eval_result.suggestions:
                        intent = ActionIntent(
                            thought=intent.thought + " [eval-retry]",
                            action=intent.action,
                            args={**intent.args, **eval_result.suggestions},
                        )
                    # If not rewinding, still open gripper after grasp_miss
                    if (
                        not rewind_on_retry
                        and intent.action == "close_gripper"
                        and act_result.message == "grasp_miss"
                        and world.robot.gripper == "closed"
                    ):
                        registry.execute(
                            "open_gripper",
                            world,
                            {},
                            ctx={"skillbook": skillbook, "recall": recall},
                        )
                    continue

                # Exhausted retries
                if eval_on_exhausted == "fail_task":
                    return _finish_failed(
                        recall,
                        event_log,
                        instruction,
                        goal_object_id,
                        step,
                        "evaluate_failed",
                        {
                            "action": intent.action,
                            "score": eval_result.score,
                            "reason": eval_result.reason,
                        },
                    )
                if process_log is not None:
                    _log_act_to_process(process_log, intent.action, act_result)
                if print_step:
                    print(
                        f"[step {step}] EVAL exhausted → continue "
                        f"(score={eval_result.score:.2f})"
                    )

            if last_result is not None:
                flow_assist.record_executed(intent, last_result)
                if last_result.ok:
                    last_result = _run_flow_followups(
                        flow_assist,
                        intent,
                        last_result,
                        world,
                        gate=gate,
                        registry=registry,
                        skillbook=skillbook,
                        recall=recall,
                        event_log=event_log,
                        process_log=process_log,
                        step=step,
                        print_step=print_step,
                    )

            if last_result and not last_result.ok and not (
                eval_result and eval_result.passed
            ):
                fail_key = f"act:{last_result.action}:{last_result.message}"
                same_fail_key, same_fail_count = _bump_fail(
                    same_fail_key, same_fail_count, fail_key
                )
                if same_fail_count >= max_same_fail:
                    return _finish_failed(
                        recall,
                        event_log,
                        instruction,
                        goal_object_id,
                        step,
                        "repeated_failure",
                        {"fail_key": fail_key, "count": same_fail_count},
                    )

            verify = verifier.check(world)
            event_log.emit(events.VERIFY_DONE, {"step": step, **verify.model_dump()})
            notes_n = len(recall.build_recall_snapshot().get("task_notes", []))
            lessons_n = len(recall.build_recall_snapshot().get("recent_lessons", []))
            if print_step:
                status = "success" if verify.success else "pending"
                print(
                    f"[step {step}] VERIFY {status} holding={world.robot.holding} "
                    f"notes={notes_n} lessons={lessons_n}"
                )

            if verify.success:
                if require_load_skill and not skill_loaded:
                    return _finish_failed(
                        recall,
                        event_log,
                        instruction,
                        goal_object_id,
                        step,
                        "skill_not_loaded",
                        {"holding": world.robot.holding},
                    )
                outcome = TaskOutcome(status="success", steps=step, verify=verify)
                recall.on_task_end(outcome, instruction, goal_object_id)
                event_log.emit(
                    events.TASK_FINISHED,
                    {
                        "status": "success",
                        "steps": step,
                        "holding": world.robot.holding,
                        "metrics": verify.metrics,
                        "skill_loaded": skill_loaded,
                    },
                )
                if process_log is not None:
                    process_log.line(f"验收通过 steps={step}")
                return outcome

            if intent.action == "done" and not verify.success:
                last_result = ActResult(ok=False, action="done", message=verify.reason)
                continue

    except KeyboardInterrupt:
        outcome = TaskOutcome(status="failed", steps=0, reason="user_abort")
        recall.on_task_end(outcome, instruction, goal_object_id)
        event_log.emit(events.TASK_FINISHED, {"status": "failed", "reason": "user_abort"})
        return outcome

    outcome = TaskOutcome(status="failed", steps=max_steps, reason="max_steps")
    recall.on_task_end(outcome, instruction, goal_object_id)
    event_log.emit(
        events.TASK_FINISHED, {"status": "failed", "reason": "max_steps", "steps": max_steps}
    )
    return outcome


def _run_flow_followups(
    flow_assist: CouplingFlowAssist,
    intent: ActionIntent,
    act_result: ActResult,
    world: WorldState,
    *,
    gate: Gate,
    registry: Any,
    skillbook: Skillbook,
    recall: RecallService,
    event_log: EventLog,
    process_log: ProcessLog | None,
    step: int,
    print_step: bool,
) -> ActResult:
    """Execute auto business steps (e.g. wipe_return after place_home)."""
    cur_intent = intent
    cur_result = act_result
    for _ in range(4):
        followups = flow_assist.followups_after(cur_intent, cur_result, world)
        if not followups:
            break
        for fu in followups:
            gate_result = gate.check(fu, world, skillbook=skillbook)
            if not gate_result.allowed:
                break
            cur_result = registry.execute(
                fu.action,
                world,
                fu.args,
                ctx={"skillbook": skillbook, "recall": recall},
            )
            event_log.emit(
                events.ACT_DONE,
                {"step": step, "attempt": 1, "flow_assist": True, **cur_result.model_dump()},
            )
            insp = (cur_result.observation or {}).get("inspection_event")
            if insp:
                event_log.emit(events.INSPECTION_EVENT, dict(insp))
                if process_log is not None:
                    process_log.line(format_inspection_line(insp))
            if process_log is not None:
                _log_act_to_process(process_log, fu.action, cur_result)
            if print_step:
                print(
                    f"[step {step}] ACT(assist) "
                    f"{'ok' if cur_result.ok else 'fail'} {cur_result.message}"
                )
            flow_assist.record_executed(fu, cur_result)
            recall.record_lesson(step, cur_result, fu.args)
            cur_intent = fu
            if not cur_result.ok:
                return cur_result
    return cur_result


def _restore_world_inplace(dst: WorldState, src: WorldState) -> None:
    """Copy checkpoint poses/gripper/holding into the live world object."""
    dst.robot = src.robot.model_copy(deep=True)
    dst.objects = {k: v.model_copy(deep=True) for k, v in src.objects.items()}


def _bump_fail(
    prev_key: str | None, prev_count: int, key: str
) -> tuple[str | None, int]:
    if key == prev_key:
        return key, prev_count + 1
    return key, 1


def _log_act_to_process(
    process_log: ProcessLog, action: str, act_result: ActResult
) -> None:
    """Only log a few physical milestones (business events already logged)."""
    if not act_result.ok:
        if action in (
            "wipe_inner",
            "measure_inner",
            "close_gripper",
            "cleaning_review",
            "rule_judge",
            "archive_record",
        ):
            process_log.line(f"  · 失败 {action}: {act_result.message}")
        return
    if action == "wipe_inner":
        process_log.line("  · 执行擦拭")
    elif action == "measure_inner":
        delta = (act_result.observation or {}).get("delta_d_mm")
        if delta is not None:
            process_log.line(f"  · 执行测量 Δd={float(delta):+.3f}")
        else:
            process_log.line("  · 执行测量")
    elif action == "return_home":
        process_log.line("  · 回到初始位")
    elif action == "close_gripper" and act_result.message.startswith("grasped_"):
        oid = act_result.message.replace("grasped_", "")
        name = {"rag": "抹布", "ruler": "测量尺", "can_cola": "易拉罐"}.get(oid, oid)
        process_log.line(f"  · 抓取 {name}")
    elif action == "lift" and "can" in (act_result.message or ""):
        process_log.line(f"  · {act_result.message}")



def _finish_failed(
    recall: RecallService,
    event_log: EventLog,
    instruction: str,
    goal_object_id: str,
    step: int,
    reason: str,
    metrics: dict[str, Any],
) -> TaskOutcome:
    outcome = TaskOutcome(status="failed", steps=step, reason=reason, metrics=metrics)
    recall.on_task_end(outcome, instruction, goal_object_id)
    event_log.emit(
        events.TASK_FINISHED, {"status": "failed", "reason": reason, **metrics}
    )
    return outcome
