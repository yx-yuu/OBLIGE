from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from edos.programbench.docker import docker_env, ensure_docker_available, trim_output
from edos.types import ExperimentConfig, TaskSpec, WorkspaceSpec


WORKSPACE_MANIFEST_NAME = "workspace_manifest.json"
CLEANROOM_EXECUTABLE_SENTINEL = "__programbench_cleanroom_executable__"


def prepare_workspace(
    *,
    experiment: ExperimentConfig,
    task: TaskSpec,
    run_id: str,
    run_dir: str,
) -> WorkspaceSpec:
    run_dir_path = Path(run_dir).resolve()
    workspace_root = Path(experiment.workspace_root)
    if not workspace_root.is_absolute():
        workspace_root = run_dir_path / workspace_root
    workspace_path = (workspace_root / run_id).resolve()
    archive_existing_workspace(workspace_path)
    workspace_path.mkdir(parents=True, exist_ok=True)

    if experiment.programbench_workspace_source == "cleanroom_image":
        materialize_programbench_cleanroom_workspace(
            experiment=experiment,
            task=task,
            workspace_path=workspace_path,
        )

    docs_path = _materialize_docs(experiment, task, workspace_path)
    docs_source_type_override = None
    if docs_path is None and experiment.programbench_workspace_source == "cleanroom_image":
        docs_path = discover_cleanroom_docs(workspace_path)
        if docs_path is not None:
            docs_source_type_override = "programbench_cleanroom_workspace"
    gold_executable = _resolve_task_path(experiment, task.gold_executable)
    if (
        gold_executable is None
        and experiment.programbench_workspace_source == "cleanroom_image"
        and (workspace_path / "executable").is_file()
    ):
        gold_executable = workspace_path / "executable"
    material = audit_task_materials(
        experiment=experiment,
        task=task,
        docs_path=docs_path,
        gold_executable=gold_executable,
        docs_source_type_override=docs_source_type_override,
    )

    for item in task.workspace_files:
        source = _resolve_task_path(experiment, item)
        if source is None:
            continue
        target = workspace_path / source.name
        if source.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
        elif source.exists():
            shutil.copy2(source, target)

    manifest = workspace_path / WORKSPACE_MANIFEST_NAME
    manifest.write_text(
        json.dumps(
            {
                "task_id": task.task_id,
                "run_id": run_id,
                "docs_path": str(docs_path) if docs_path else None,
                "gold_executable": str(gold_executable) if gold_executable else None,
                "workspace_files": task.workspace_files,
                **material,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return WorkspaceSpec(
        task_id=task.task_id,
        run_id=run_id,
        workspace_path=str(workspace_path),
        docs_path=str(docs_path) if docs_path else None,
        gold_executable=str(gold_executable) if gold_executable else None,
        candidate_path=str(workspace_path),
        task_material_status=material["task_material_status"],
        task_material_warnings=material["task_material_warnings"],
        docs_source_type=material["docs_source_type"],
        docs_materialized=material["docs_materialized"],
        gold_executable_available=material["gold_executable_available"],
        programbench_cleanroom_image=material["programbench_cleanroom_image"],
        programbench_tests_json=material["programbench_tests_json"],
        programbench_tests_json_available=material["programbench_tests_json_available"],
    )


def preview_task_materials(
    *,
    experiment: ExperimentConfig,
    task: TaskSpec,
) -> dict[str, object]:
    docs_candidate = _resolve_task_path(experiment, task.docs_path)
    cleanroom_requested = experiment.programbench_workspace_source == "cleanroom_image"
    metadata_summary = _is_programbench_metadata_summary(task)
    inline_docs_available = bool(task.docs) and not (
        cleanroom_requested and metadata_summary
    )
    docs_available = inline_docs_available or bool(
        docs_candidate and docs_candidate.exists()
    )
    docs_source_type_override = None
    if cleanroom_requested and task.metadata.get("image_name"):
        docs_available = True
        if not inline_docs_available and not (docs_candidate and docs_candidate.exists()):
            docs_source_type_override = "programbench_cleanroom_workspace_expected"
    gold_executable = _resolve_task_path(experiment, task.gold_executable)
    if cleanroom_requested and gold_executable is None and task.metadata.get("image_name"):
        gold_executable = Path(CLEANROOM_EXECUTABLE_SENTINEL)
    return audit_task_materials(
        experiment=experiment,
        task=task,
        docs_path=docs_candidate if docs_available and docs_candidate else None,
        gold_executable=gold_executable,
        docs_materialized_override=docs_available,
        docs_source_type_override=docs_source_type_override,
    )


def materialize_programbench_cleanroom_workspace(
    *,
    experiment: ExperimentConfig,
    task: TaskSpec,
    workspace_path: Path,
) -> None:
    image_name = str(task.metadata.get("image_name") or "")
    if not image_name:
        raise ValueError(
            f"Task {task.task_id} does not include ProgramBench image_name metadata"
        )
    image = f"{image_name}:{experiment.programbench_inference_image_tag}"
    docker = experiment.programbench_docker_executable or "docker"
    ensure_docker_available(
        context=f"ProgramBench cleanroom workspace for {task.task_id}",
        docker_executable=docker,
        docker_host=experiment.programbench_docker_host,
    )
    env = docker_env(docker_host=experiment.programbench_docker_host)
    created = subprocess.run(
        [docker, "create", "--network", "none", image, "sleep", "infinity"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=env,
        timeout=experiment.timeout_seconds,
    )
    if created.returncode != 0:
        raise RuntimeError(
            "Failed to create ProgramBench cleanroom container for "
            f"{task.task_id}: {trim_output(created.stderr or created.stdout)}"
        )
    container_id = created.stdout.strip()
    if not container_id:
        raise RuntimeError(f"Docker did not return a container id for {task.task_id}")
    try:
        copied = subprocess.run(
            [docker, "cp", f"{container_id}:/workspace/.", str(workspace_path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=env,
            timeout=experiment.timeout_seconds,
        )
        if copied.returncode != 0:
            raise RuntimeError(
                "Failed to copy ProgramBench cleanroom workspace for "
                f"{task.task_id}: {trim_output(copied.stderr or copied.stdout)}"
            )
    finally:
        subprocess.run(
            [docker, "rm", "-f", container_id],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            env=env,
            timeout=30,
        )


def discover_cleanroom_docs(workspace_path: Path) -> Path | None:
    preferred = [
        "README.md",
        "README",
        "docs",
        "doc",
        "documentation",
        "DOCUMENTATION.md",
        "TASK_DOCS.md",
    ]
    for relative in preferred:
        candidate = workspace_path / relative
        if candidate.exists():
            return candidate
    for candidate in sorted(workspace_path.iterdir()):
        if candidate.name.lower().startswith("readme") and candidate.is_file():
            return candidate
    return None


def archive_existing_workspace(workspace_path: Path) -> Path | None:
    if not workspace_path.exists():
        return None
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    archive_path = workspace_path.with_name(f"{workspace_path.name}_archive_{timestamp}")
    counter = 1
    while archive_path.exists():
        archive_path = workspace_path.with_name(
            f"{workspace_path.name}_archive_{timestamp}_{counter}"
        )
        counter += 1
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(workspace_path), str(archive_path))
    return archive_path


def _materialize_docs(
    experiment: ExperimentConfig,
    task: TaskSpec,
    workspace_path: Path,
) -> Path | None:
    if task.docs_path:
        source = _resolve_task_path(experiment, task.docs_path)
        if source and source.exists():
            target = workspace_path / source.name
            if source.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
            return target
    if task.docs:
        if (
            experiment.programbench_workspace_source == "cleanroom_image"
            and _is_programbench_metadata_summary(task)
        ):
            return None
        target = workspace_path / "TASK_DOCS.md"
        target.write_text(task.docs, encoding="utf-8")
        return target
    return None


def _resolve_task_path(experiment: ExperimentConfig, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    if experiment.programbench_root:
        candidate = Path(experiment.programbench_root) / path
        if candidate.exists():
            return candidate
    return path


def audit_task_materials(
    *,
    experiment: ExperimentConfig,
    task: TaskSpec,
    docs_path: Path | None,
    gold_executable: Path | None,
    docs_materialized_override: bool | None = None,
    docs_source_type_override: str | None = None,
) -> dict[str, object]:
    docs_materialized = (
        docs_materialized_override
        if docs_materialized_override is not None
        else bool(docs_path and docs_path.exists())
    )
    cleanroom_requested = experiment.programbench_workspace_source == "cleanroom_image"
    cleanroom_sentinel = bool(
        gold_executable and str(gold_executable) == CLEANROOM_EXECUTABLE_SENTINEL
    )
    gold_available = bool(
        gold_executable and (cleanroom_sentinel or gold_executable.exists())
    )
    has_programbench_metadata = bool(
        task.metadata.get("image_name")
        or task.metadata.get("task_yaml")
        or task.metadata.get("tests_json")
    )
    docs_source_type = docs_source_type_override or docs_source_type_for_task(
        task, docs_materialized
    )
    tests_json = _resolve_task_path(
        experiment,
        str(task.metadata.get("tests_json") or ""),
    )
    tests_json_available = bool(tests_json and tests_json.exists())
    image_name = str(task.metadata.get("image_name") or "")

    warnings: list[str] = []
    if not docs_materialized:
        warnings.append("missing_docs")
    if not gold_available:
        warnings.append("missing_local_gold_executable")
    if has_programbench_metadata and not gold_available:
        warnings.append("requires_programbench_cleanroom_or_gold_export")
    if has_programbench_metadata and not tests_json_available:
        warnings.append("missing_programbench_tests_json")

    if cleanroom_requested and has_programbench_metadata and gold_available:
        status = "programbench_cleanroom_workspace"
    elif docs_materialized and gold_available:
        status = "local_complete"
    elif has_programbench_metadata and not gold_available:
        status = "programbench_cleanroom_metadata_only"
    elif docs_materialized:
        status = "local_docs_only"
    elif gold_available:
        status = "local_gold_only"
    else:
        status = "missing_task_materials"

    return {
        "task_material_status": status,
        "task_material_warnings": ";".join(warnings),
        "docs_source_type": docs_source_type,
        "docs_materialized": docs_materialized,
        "gold_executable_available": gold_available,
        "programbench_cleanroom_image": image_name,
        "programbench_tests_json": str(tests_json) if tests_json else "",
        "programbench_tests_json_available": tests_json_available,
    }


def docs_source_type_for_task(task: TaskSpec, docs_materialized: bool) -> str:
    if not docs_materialized:
        return "none"
    if task.docs_path:
        return "file_or_directory"
    if (
        task.metadata.get("image_name")
        and str(task.docs).startswith("ProgramBench instance ")
    ):
        return "inline_programbench_metadata_summary"
    if task.docs:
        return "inline_task_docs"
    return "none"


def _is_programbench_metadata_summary(task: TaskSpec) -> bool:
    return bool(
        task.metadata.get("image_name")
        and str(task.docs).startswith("ProgramBench instance ")
    )
