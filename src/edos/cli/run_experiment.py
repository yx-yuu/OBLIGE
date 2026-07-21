from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from edos.adapters.factory import make_adapter
from edos.config import load_experiment_config
from edos.instrumentation.logger import utc_now
from edos.jsonutil import to_jsonable
from edos.programbench.tasks import load_task_list
from edos.programbench.workspace import preview_task_materials
from edos.types import ConditionSpec, ExperimentConfig, TaskSpec


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")


def compact_task_name(task_id: str) -> str:
    name = safe_name(task_id) or "task"
    if len(name) <= 80:
        return name
    digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:8]
    return f"{name[:71]}_{digest}"


def experiment_for_repeat(config: ExperimentConfig, repeat_index: int) -> ExperimentConfig:
    repeat_label = f"rep{repeat_index:03d}"
    return type(config)(
        **{
            **config.__dict__,
            "seed": config.seed + repeat_index,
            "repeat_index": repeat_index,
            "repeat_label": repeat_label,
        }
    )


def apply_cli_overrides(
    config: ExperimentConfig,
    *,
    experiment_name: str | None = None,
    output_dir: str | None = None,
    repeats: int | None = None,
) -> ExperimentConfig:
    values = {**config.__dict__}
    if experiment_name:
        values["name"] = experiment_name
    if output_dir:
        values["output_dir"] = output_dir
    if repeats is not None:
        values["repeats"] = max(1, repeats)
    return type(config)(**values)


def build_run_id(
    *,
    task_id: str,
    condition: str,
    target_level: str,
    verifier_exposure_condition: str,
    repeat_label: str,
    include_repeat: bool,
    entry_surface: str = "",
) -> str:
    parts = [
        task_id,
        condition,
        target_level,
        verifier_exposure_condition,
        entry_surface,
    ]
    if include_repeat:
        parts.append(repeat_label)
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"{compact_task_name(task_id)}__pb_{digest}"


def archive_existing_path(path: Path) -> Path | None:
    if not path.exists():
        return None
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    archive_root = path.parent / "_archives"
    archive_root.mkdir(parents=True, exist_ok=True)
    archive_path = archive_root / f"{path.name}_archive_{timestamp}"
    counter = 1
    while archive_path.exists():
        archive_path = archive_root / f"{path.name}_archive_{timestamp}_{counter}"
        counter += 1
    shutil.move(str(path), str(archive_path))
    return archive_path


def archive_existing_run_dir(run_dir: Path) -> Path | None:
    return archive_existing_path(run_dir)


def archive_existing_output_dir(output_dir: Path) -> Path | None:
    return archive_existing_path(output_dir)


def select_tasks(
    tasks: list[TaskSpec],
    *,
    task_start: int = 0,
    task_stop: int | None = None,
    task_limit: int | None = None,
    shard_index: int | None = None,
    shard_count: int | None = None,
) -> list[TaskSpec]:
    start = max(0, task_start)
    stop = task_stop if task_stop is not None else len(tasks)
    selected = tasks[start : max(start, stop)]
    if task_limit is not None:
        selected = selected[: max(0, task_limit)]
    if shard_count is not None:
        count = max(1, shard_count)
        index = 0 if shard_index is None else shard_index
        if index < 0 or index >= count:
            raise ValueError(
                f"shard_index must be in [0, {count - 1}], got {index}"
            )
        selected = [
            task
            for offset, task in enumerate(selected)
            if offset % count == index
        ]
    return selected


def select_conditions(
    conditions: list[ConditionSpec],
    *,
    condition_names: list[str],
) -> list[ConditionSpec]:
    names = {name for name in condition_names if name}
    if not names:
        return conditions
    selected = [condition for condition in conditions if condition.condition in names]
    missing = sorted(names - {condition.condition for condition in selected})
    if missing:
        raise ValueError(f"Unknown condition name(s): {', '.join(missing)}")
    return selected


def is_completed_run(run_dir: str | Path) -> bool:
    current = Path(run_dir)
    required = [
        "metadata.json",
        "usage.json",
        "programbench_score.json",
        "failure_label.json",
        "events.jsonl",
    ]
    if not all((current / name).exists() for name in required):
        return False
    try:
        metadata = json.loads(
            (current / "metadata.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return False
    return bool(metadata.get("ended_at"))


def load_existing_run_summary(run_dir: str | Path) -> dict:
    current = Path(run_dir)
    metadata = load_json_if_exists(current / "metadata.json")
    failure = load_json_if_exists(current / "failure_label.json")
    score = load_json_if_exists(current / "programbench_score.json")
    return {
        "run_id": metadata.get("run_id", current.name),
        "run_dir": str(current),
        "failure_label": failure.get("failure_label"),
        "score_status": score.get("score_status"),
    }


def load_json_if_exists(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def planned_run_manifest(
    *,
    experiment: ExperimentConfig,
    task: TaskSpec,
    condition: ConditionSpec,
    run_id: str,
    run_dir: str,
) -> dict:
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "run_dir": str(run_dir),
        "experiment_name": experiment.name,
        "repeat_index": experiment.repeat_index,
        "repeat_label": experiment.repeat_label,
        "repeat_count": experiment.repeats,
        "task": to_jsonable(task),
        "condition": to_jsonable(condition),
        "agent_runtime": experiment.agent_runtime,
        "model": experiment.model,
        "created_at": utc_now(),
        "status": "planned",
        "started_at": None,
        "ended_at": None,
        "skip_reason": "",
        "failure_label": None,
        "score_status": None,
    }


def build_task_material_audit(
    *,
    experiment: ExperimentConfig,
    tasks: list[TaskSpec],
) -> dict:
    rows = []
    summary: dict[str, int] = {}
    for task in tasks:
        material = preview_task_materials(experiment=experiment, task=task)
        status = str(material.get("task_material_status") or "unknown")
        summary[status] = summary.get(status, 0) + 1
        rows.append(
            {
                "task_id": task.task_id,
                "difficulty": task.difficulty,
                "category": task.category,
                **material,
            }
        )
    return {
        "task_count": len(rows),
        "summary": summary,
        "tasks": rows,
    }


def validate_task_material_statuses(
    audit: dict,
    *,
    allowed_statuses: list[str],
) -> None:
    allowed = {status for status in allowed_statuses if status}
    if not allowed:
        return
    rejected = [
        row
        for row in audit.get("tasks", [])
        if row.get("task_material_status") not in allowed
    ]
    if not rejected:
        return
    preview = ", ".join(
        f"{row.get('task_id')}={row.get('task_material_status')}"
        for row in rejected[:5]
    )
    suffix = "" if len(rejected) <= 5 else f", ... +{len(rejected) - 5} more"
    raise ValueError(
        "Task material status check failed; allowed="
        f"{sorted(allowed)}; rejected={preview}{suffix}"
    )


def write_run_manifest(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--experiment-name")
    parser.add_argument("--output-dir")
    parser.add_argument("--repeats", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--skip-completed", action="store_true")
    parser.add_argument("--task-start", type=int, default=0)
    parser.add_argument("--task-stop", type=int)
    parser.add_argument("--task-limit", type=int)
    parser.add_argument("--shard-index", type=int)
    parser.add_argument("--shard-count", type=int)
    parser.add_argument(
        "--condition",
        action="append",
        default=[],
        help="Run only this condition name. Can be passed multiple times.",
    )
    parser.add_argument(
        "--require-task-material-status",
        action="append",
        default=[],
        help=(
            "Allowed task_material_status value. Can be passed multiple times. "
            "Use local_complete for paper-grade local material runs."
        ),
    )
    args = parser.parse_args()

    config = apply_cli_overrides(
        load_experiment_config(args.config),
        experiment_name=args.experiment_name,
        output_dir=args.output_dir,
        repeats=args.repeats,
    )
    tasks = select_tasks(
        load_task_list(config.task_list),
        task_start=args.task_start,
        task_stop=args.task_stop,
        task_limit=args.task_limit,
        shard_index=args.shard_index,
        shard_count=args.shard_count,
    )
    conditions = select_conditions(config.conditions, condition_names=args.condition)
    task_material_audit = build_task_material_audit(experiment=config, tasks=tasks)
    try:
        validate_task_material_statuses(
            task_material_audit,
            allowed_statuses=args.require_task_material_status,
        )
    except ValueError as exc:
        parser.error(str(exc))
    output_dir = Path(config.output_dir)
    if not args.resume:
        archive_existing_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "experiment.resolved.json").open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "config": args.config,
                "experiment_name": config.name,
                "task_count": len(tasks),
                "task_start": args.task_start,
                "task_stop": args.task_stop,
                "task_limit": args.task_limit,
                "shard_index": args.shard_index,
                "shard_count": args.shard_count,
                "repeats": config.repeats,
                "resume": args.resume,
                "skip_completed": args.skip_completed,
                "task_material_summary": task_material_audit["summary"],
                "required_task_material_statuses": args.require_task_material_status,
                "conditions": [item.__dict__ for item in conditions],
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )
        handle.write("\n")
    with (output_dir / "task_material_audit.json").open("w", encoding="utf-8") as handle:
        json.dump(task_material_audit, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    adapter = make_adapter(config)
    results = []
    planned_runs = []
    include_repeat = config.repeats > 1
    for repeat_index in range(config.repeats):
        repeat_config = experiment_for_repeat(config, repeat_index)
        for task in tasks:
            for condition in conditions:
                run_id = build_run_id(
                    task_id=task.task_id,
                    condition=condition.condition,
                    target_level=condition.target_level,
                    verifier_exposure_condition=condition.verifier_exposure_condition,
                    entry_surface=condition.entry_surface,
                    repeat_label=repeat_config.repeat_label,
                    include_repeat=include_repeat,
                )
                run_dir_path = output_dir / run_id
                run_dir = str(run_dir_path)
                manifest = planned_run_manifest(
                    experiment=repeat_config,
                    task=task,
                    condition=condition,
                    run_id=run_id,
                    run_dir=run_dir,
                )
                planned_runs.append(manifest)
                if args.resume and args.skip_completed and is_completed_run(run_dir_path):
                    existing = load_existing_run_summary(run_dir_path)
                    manifest.update(
                        {
                            "status": "skipped",
                            "ended_at": utc_now(),
                            "skip_reason": "completed_run_present",
                            "failure_label": existing.get("failure_label"),
                            "score_status": existing.get("score_status"),
                        }
                    )
                    write_run_manifest(run_dir_path / "run_manifest.json", manifest)
                    results.append(
                        {
                            **existing,
                            "repeat_index": repeat_config.repeat_index,
                            "repeat_label": repeat_config.repeat_label,
                            "status": "skipped",
                            "skip_reason": "completed_run_present",
                        }
                    )
                    continue
                if run_dir_path.exists():
                    archive_existing_run_dir(run_dir_path)
                manifest.update({"status": "running", "started_at": utc_now()})
                write_run_manifest(run_dir_path / "run_manifest.json", manifest)
                try:
                    result = adapter.run_task(
                        experiment=repeat_config,
                        task=task,
                        condition=condition,
                        run_id=run_id,
                        run_dir=run_dir,
                    )
                except BaseException as exc:
                    manifest.update(
                        {
                            "status": "failed",
                            "ended_at": utc_now(),
                            "failure_label": f"harness_exception:{type(exc).__name__}",
                            "error": str(exc),
                        }
                    )
                    write_run_manifest(run_dir_path / "run_manifest.json", manifest)
                    raise
                manifest.update(
                    {
                        "status": "complete",
                        "ended_at": utc_now(),
                        "failure_label": result.failure_label,
                        "score_status": result.score.get("score_status"),
                    }
                )
                write_run_manifest(run_dir_path / "run_manifest.json", manifest)
                results.append(
                    {
                        "run_id": result.run_id,
                        "run_dir": result.run_dir,
                        "repeat_index": repeat_config.repeat_index,
                        "repeat_label": repeat_config.repeat_label,
                        "status": "complete",
                        "skip_reason": "",
                        "failure_label": result.failure_label,
                        "score_status": result.score.get("score_status"),
                    }
                )
    with (output_dir / "planned_runs.json").open("w", encoding="utf-8") as handle:
        json.dump(to_jsonable(planned_runs), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    with (output_dir / "run_index.json").open("w", encoding="utf-8") as handle:
        json.dump(results, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    skipped = sum(1 for item in results if item.get("status") == "skipped")
    print(f"Wrote {len(results)} run records to {output_dir}; skipped={skipped}")


if __name__ == "__main__":
    main()
