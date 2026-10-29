from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv

from actforge.adapters.factory import create_sim
from actforge.adapters.policy_script import build_script_policy
from actforge.capabilities.registry import build_default_registry
from actforge.evaluate.step_eval import StepEvaluator, load_evaluate_config
from actforge.kernel.state_machine import run_task
from actforge.policy_gate.rules import Gate
from actforge.recall.service import RecallService
from actforge.skillbook.catalog import Skillbook
from actforge.util.config import load_recall_config, load_scene, load_task, resolve_goal_object_id
from actforge.util.logging_jsonl import EventLog
from actforge.util.process_log import ProcessLog, write_inspection_summary
from actforge.util.task_router import resolve_task_preset
from actforge.verify.coupling_clean import CouplingCleanVerifier
from actforge.verify.pick_can import PickCanVerifier

app = typer.Typer(
    name="actforge",
    help="ActForge Harness — embodied simulation demos",
    no_args_is_help=True,
)


@app.callback()
def _root() -> None:
    """ActForge Harness CLI."""


def _resolve(path: str, root: Path) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    return (root / p).resolve()


@app.command("run")
def run(
    instruction: str = typer.Option(
        "把桌上的易拉罐拿起来",
        "--instruction",
        "-i",
        help="自然语言指令；用于自动选择任务（抓罐 / 接箍清洁测量）",
    ),
    task_id: Optional[str] = typer.Option(
        None,
        "--task-id",
        help="强制任务: pick_can | coupling_clean；默认根据 instruction 自动推断",
    ),
    scene: Optional[str] = typer.Option(
        None, "--scene", help="覆盖场景 YAML；默认由任务预设决定"
    ),
    task: Optional[str] = typer.Option(
        None, "--task", help="覆盖任务 YAML；默认由任务预设决定"
    ),
    skills_dir: str = typer.Option("skills", "--skills-dir"),
    recall_config: str = typer.Option("configs/recall.yaml", "--recall-config"),
    tasks_catalog: str = typer.Option("configs/tasks.yaml", "--tasks-catalog"),
    policy: str = typer.Option("script", "--policy", help="script | llm"),
    sim: str = typer.Option("mock", "--sim", help="mock | pybullet"),
    gui: bool = typer.Option(False, "--gui", help="Show PyBullet GUI (pybullet only)"),
    real_time: bool = typer.Option(False, "--real-time", help="Slow down GUI to wall clock"),
    max_steps: Optional[int] = typer.Option(None, "--max-steps"),
    runs_dir: str = typer.Option("runs", "--runs-dir"),
    prompt: Optional[str] = typer.Option(None, "--prompt", help="覆盖 system prompt 路径"),
    evaluate_config: str = typer.Option("configs/evaluate.yaml", "--evaluate-config"),
    no_evaluate: bool = typer.Option(False, "--no-evaluate", help="Disable per-step auto evaluation"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Run an embodied task. Task is chosen from instruction unless --task-id is set."""
    load_dotenv()
    root = Path.cwd()

    catalog_path = _resolve(tasks_catalog, root)
    resolved_id, preset = resolve_task_preset(
        instruction, catalog_path, task_id=task_id
    )

    scene_path = _resolve(scene or preset["scene"], root)
    task_path = _resolve(task or preset["task"], root)
    prompt_path = _resolve(prompt or preset["prompt"], root)
    skills_path = _resolve(skills_dir, root)
    recall_path = _resolve(recall_config, root)
    runs_path = _resolve(runs_dir, root)

    world = load_scene(scene_path)
    task_cfg = load_task(task_path)
    recall_cfg = load_recall_config(recall_path)

    goal = task_cfg.get("goal", {})
    default_goal = goal.get("object_id", "can_cola")
    aliases = task_cfg.get("aliases") or {}
    goal_object_id = resolve_goal_object_id(instruction, aliases, default_goal)
    # Coupling scene uses coupling_A/B; never keep a stale bare "coupling" id
    if resolved_id == "coupling_clean" and goal_object_id not in ("coupling_A", "coupling_B"):
        goal_object_id = "coupling_A"
    limits = dict(task_cfg.get("limits", {}))
    if max_steps is not None:
        limits["max_steps"] = max_steps

    skills_cfg = task_cfg.get("skills") or {}
    require_load = bool(skills_cfg.get("require_load_for_demo", False))

    eval_path = _resolve(evaluate_config, root)
    evaluate_cfg = load_evaluate_config(eval_path if eval_path.exists() else None)
    if no_evaluate:
        evaluate_cfg["enabled"] = False
    evaluator = (
        StepEvaluator(
            threshold=float(evaluate_cfg.get("threshold", 0.7)),
            goal_object_id=goal_object_id,
        )
        if evaluate_cfg.get("enabled")
        else None
    )

    run_id = uuid.uuid4().hex[:12]
    run_dir = runs_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    event_log = EventLog(run_id, run_dir / "events.jsonl")
    process_path = run_dir / "process.log"
    process_log = ProcessLog(process_path, echo=True)

    skillbook = Skillbook(skills_path)
    recall = RecallService(recall_cfg, event_log=event_log)

    try:
        backend = create_sim(sim, gui=gui, real_time=real_time)
    except Exception as e:  # noqa: BLE001
        process_log.close()
        typer.echo(f"Failed to create sim backend '{sim}': {e}", err=True)
        raise typer.Exit(code=2)

    if hasattr(backend, "reset") and sim.lower() not in ("mock", "mocksim"):
        world = backend.reset(world)

    registry = build_default_registry(backend)
    gate = Gate()

    if resolved_id == "coupling_clean":
        expected_wp = goal.get("expected_workpieces") or ["A", "B"]
        verifier: object = CouplingCleanVerifier(
            require_wiped=bool(goal.get("require_wiped", True)),
            require_measured=bool(goal.get("require_measured", True)),
            require_empty_hand=bool(goal.get("require_empty_hand", True)),
            require_returned_home=bool(goal.get("require_returned_home", True)),
            expected_workpieces=list(expected_wp),
        )
    else:
        min_lift_z = float(goal.get("min_lift_z", 0.10))
        verifier = PickCanVerifier(
            object_id=goal_object_id,
            min_lift_z=min_lift_z,
            table_z=world.table_z,
            require_returned_home=bool(goal.get("require_returned_home", True)),
        )

    if policy == "script":
        pol: object = build_script_policy(resolved_id, goal_object_id=goal_object_id)
    elif policy == "llm":
        from actforge.adapters.llm_openai import LLMPolicy

        pol = LLMPolicy(system_prompt_path=prompt_path, verbose=verbose)
    else:
        process_log.close()
        typer.echo(f"Unknown policy: {policy}", err=True)
        raise typer.Exit(code=2)

    task_title = {
        "coupling_clean": "接箍中径检测",
        "pick_can": "桌面抓取",
    }.get(resolved_id, resolved_id)
    process_log.line(f"任务: {task_title}")
    process_log.line(f"指令: {instruction}")
    process_log.line("")
    if verbose:
        typer.echo(f"goal_object_id={goal_object_id}")
        typer.echo(f"require_load_skill={require_load}")
        typer.echo(
            f"evaluate_enabled={evaluate_cfg.get('enabled')} threshold={evaluate_cfg.get('threshold')}"
        )

    try:
        outcome = run_task(
            instruction=instruction,
            world=world,
            policy=pol,  # type: ignore[arg-type]
            gate=gate,
            registry=registry,
            verifier=verifier,
            limits=limits,
            skillbook=skillbook,
            recall=recall,
            event_log=event_log,
            goal_object_id=goal_object_id,
            print_step=verbose,  # 逐步 DECIDE/GATE/ACT 仅 --verbose
            verbose=verbose,
            require_load_skill=require_load,
            evaluator=evaluator,
            evaluate_cfg=evaluate_cfg,
            sim=backend,
            process_log=process_log,
        )
    except KeyboardInterrupt:
        process_log.line("结果: failed (user_abort)")
        process_log.close()
        typer.echo(f"process_log={process_path}")
        if hasattr(backend, "close"):
            backend.close()
        raise typer.Exit(code=1)
    finally:
        if hasattr(backend, "close"):
            backend.close()

    holding = world.robot.holding
    flags = world.task_flags or {}
    process_log.line("")
    if resolved_id == "coupling_clean":
        results = flags.get("workpiece_results") or {}
        write_inspection_summary(process_log, list(flags.get("inspection_log") or []))
        for wp in flags.get("archived_workpieces") or []:
            r = results.get(wp) or {}
            q = "合格" if r.get("quality") == "qualified" else "不合格"
            d = r.get("delta_d_mm")
            d_s = f" Δd={float(d):+.3f}" if d is not None else ""
            process_log.line(f"接箍{wp}: {q}{d_s}")
        process_log.line(
            f"结果: {outcome.status} | steps={outcome.steps} | "
            f"archived={flags.get('archived_workpieces')}"
        )
    else:
        lift_z = None
        if holding and holding in world.objects:
            lift_z = world.objects[holding].xyz.z - world.table_z
        process_log.line(
            f"结果: {outcome.status} | steps={outcome.steps} | "
            f"holding={holding} | lift_z="
            f"{f'{lift_z:.2f}' if lift_z is not None else 'n/a'}"
        )
    if outcome.reason:
        process_log.line(f"原因: {outcome.reason}")
    process_log.line(f"明细事件: {run_dir / 'events.jsonl'}")
    process_log.close()

    typer.echo(f"process_log={process_path}")

    if outcome.status != "success":
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
