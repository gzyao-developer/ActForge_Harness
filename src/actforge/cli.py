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

    skillbook = Skillbook(skills_path)
    recall = RecallService(recall_cfg, event_log=event_log)

    try:
        backend = create_sim(sim, gui=gui, real_time=real_time)
    except Exception as e:  # noqa: BLE001
        typer.echo(f"Failed to create sim backend '{sim}': {e}", err=True)
        raise typer.Exit(code=2)

    if hasattr(backend, "reset") and sim.lower() not in ("mock", "mocksim"):
        world = backend.reset(world)

    registry = build_default_registry(backend)
    gate = Gate()

    if resolved_id == "coupling_clean":
        verifier: object = CouplingCleanVerifier(
            require_wiped=bool(goal.get("require_wiped", True)),
            require_measured=bool(goal.get("require_measured", True)),
            require_empty_hand=bool(goal.get("require_empty_hand", True)),
            require_returned_home=bool(goal.get("require_returned_home", True)),
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
        typer.echo(f"Unknown policy: {policy}", err=True)
        raise typer.Exit(code=2)

    typer.echo(f"task_id={resolved_id} scene={scene_path.name} policy={policy} sim={sim}")
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
            print_step=True,
            verbose=verbose,
            require_load_skill=require_load,
            evaluator=evaluator,
            evaluate_cfg=evaluate_cfg,
            sim=backend,
        )
    except KeyboardInterrupt:
        typer.echo("TASK_RESULT status=failed reason=user_abort")
        typer.echo(f"log={run_dir / 'events.jsonl'}")
        if hasattr(backend, "close"):
            backend.close()
        raise typer.Exit(code=1)
    finally:
        if hasattr(backend, "close"):
            backend.close()

    holding = world.robot.holding
    flags = world.task_flags or {}
    extra = ""
    if resolved_id == "coupling_clean":
        extra = (
            f" wiped={flags.get('coupling_wiped')} measured={flags.get('coupling_measured')}"
            f" diameter_mm={flags.get('inner_diameter_mm')}"
        )
        lift_str = "n/a"
    else:
        lift_z = None
        if holding and holding in world.objects:
            lift_z = world.objects[holding].xyz.z - world.table_z
        lift_str = f"{lift_z:.2f}" if lift_z is not None else "n/a"

    typer.echo(
        f"TASK_RESULT status={outcome.status} steps={outcome.steps} "
        f"holding={holding} lift_z={lift_str}{extra}"
    )
    if outcome.reason:
        typer.echo(f"fail_reason={outcome.reason}")
    typer.echo(f"log={run_dir / 'events.jsonl'}")
    typer.echo(f"sim={sim} task_id={resolved_id}")

    if outcome.status != "success":
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
