from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from edos.types import TaskSpec


def load_task_list(path: str | Path) -> list[TaskSpec]:
    with Path(path).open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if isinstance(raw, dict):
        items = raw.get("tasks", [])
    elif isinstance(raw, list):
        items = raw
    else:
        raise ValueError(f"Unsupported task list format: {type(raw).__name__}")
    tasks: list[TaskSpec] = []
    for item in items:
        tasks.append(
            TaskSpec(
                task_id=item["task_id"],
                difficulty=item.get("difficulty", "unknown"),
                category=item.get("category", "unknown"),
                docs=item.get("docs", ""),
                gold_command=item.get("gold_command"),
                docs_path=item.get("docs_path"),
                gold_executable=item.get("gold_executable"),
                workspace_files=item.get("workspace_files", []),
                scorer_command=item.get("scorer_command", []),
                metadata=item.get("metadata", {}),
            )
        )
    return tasks


def load_programbench_catalog(
    programbench_root: str | Path,
    *,
    limit: int | None = None,
    difficulty: set[str] | None = None,
    category: set[str] | None = None,
    exclude_repository_prefixes: set[str] | None = None,
    seed: int | None = None,
    per_difficulty_limit: int | None = None,
    per_category_limit: int | None = None,
) -> list[TaskSpec]:
    root = Path(programbench_root)
    tasks_dir = root / "src" / "programbench" / "data" / "tasks"
    if not tasks_dir.exists():
        raise FileNotFoundError(f"ProgramBench tasks directory not found: {tasks_dir}")
    tasks: list[TaskSpec] = []
    for task_yaml in sorted(tasks_dir.glob("*/task.yaml")):
        raw = parse_simple_yaml(task_yaml)
        diff = str(raw.get("difficulty", "unknown"))
        if difficulty and diff not in difficulty:
            continue
        instance_id = task_yaml.parent.name
        repository = str(raw.get("repository", ""))
        if repository_matches_prefix(repository, exclude_repository_prefixes):
            continue
        language = str(raw.get("language", "unknown"))
        if category and language not in category:
            continue
        tasks.append(
            TaskSpec(
                task_id=instance_id,
                difficulty=diff,
                category=language,
                docs=f"ProgramBench instance {instance_id} from {repository}",
                metadata={
                    "repository": repository,
                    "commit": raw.get("commit"),
                    "language": language,
                    "task_yaml": str(task_yaml),
                    "tests_json": str(task_yaml.parent / "tests.json"),
                    "image_name": image_name_from_instance_id(instance_id),
                    "eval_clean_hashes": raw.get("eval_clean_hashes", []),
                },
            )
        )
    return select_programbench_tasks(
        tasks,
        limit=limit,
        seed=seed,
        per_difficulty_limit=per_difficulty_limit,
        per_category_limit=per_category_limit,
    )


def repository_matches_prefix(
    repository: str,
    prefixes: set[str] | None,
) -> bool:
    if not prefixes:
        return False
    lowered = repository.lower()
    return any(lowered.startswith(prefix.lower()) for prefix in prefixes)


def write_task_list(
    path: str | Path,
    tasks: list[TaskSpec],
    *,
    metadata: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "tasks": [
            {
                "task_id": task.task_id,
                "difficulty": task.difficulty,
                "category": task.category,
                "docs": task.docs,
                "metadata": task.metadata,
            }
            for task in tasks
        ]
    }
    if metadata:
        payload["metadata"] = metadata
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def select_programbench_tasks(
    tasks: list[TaskSpec],
    *,
    limit: int | None = None,
    seed: int | None = None,
    per_difficulty_limit: int | None = None,
    per_category_limit: int | None = None,
) -> list[TaskSpec]:
    selected = list(tasks)
    if seed is not None:
        rng = random.Random(seed)
        rng.shuffle(selected)
    if per_difficulty_limit is not None:
        selected = cap_by_field(
            selected,
            field_name="difficulty",
            limit=per_difficulty_limit,
        )
    if per_category_limit is not None:
        selected = cap_by_field(
            selected,
            field_name="category",
            limit=per_category_limit,
        )
    if limit is not None:
        selected = selected[:limit]
    if seed is not None or per_difficulty_limit is not None or per_category_limit is not None:
        selected = sorted(selected, key=lambda task: (task.difficulty, task.category, task.task_id))
    return selected


def cap_by_field(
    tasks: list[TaskSpec],
    *,
    field_name: str,
    limit: int,
) -> list[TaskSpec]:
    if limit < 1:
        return []
    counts: dict[str, int] = {}
    selected: list[TaskSpec] = []
    for task in tasks:
        value = str(getattr(task, field_name))
        if counts.get(value, 0) >= limit:
            continue
        counts[value] = counts.get(value, 0) + 1
        selected.append(task)
    return selected


def parse_simple_yaml(path: str | Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    current_key: str | None = None
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and current_key:
            result.setdefault(current_key, []).append(_parse_scalar(stripped[2:].strip()))
            continue
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            current_key = key
            if value:
                result[key] = _parse_scalar(value)
            else:
                result[key] = []
    return result


def _parse_scalar(value: str) -> Any:
    if value in {"true", "false"}:
        return value == "true"
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    return value


def image_name_from_instance_id(instance_id: str, docker_org: str = "programbench") -> str:
    return f"{docker_org}/{instance_id.replace('__', '_1776_')}"
