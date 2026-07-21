from __future__ import annotations

import argparse
import json
from pathlib import Path

from edos.config import load_experiment_config
from edos.jsonutil import to_jsonable
from edos.programbench.tasks import load_task_list
from edos.programbench.workspace import preview_task_materials


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument(
        "--require-status",
        action="append",
        default=[],
        help=(
            "Allowed task_material_status value. Can be passed multiple times. "
            "Exits 2 when any task is outside the allowed set."
        ),
    )
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    experiment = load_experiment_config(args.config)
    rows = []
    for task in load_task_list(experiment.task_list):
        material = preview_task_materials(experiment=experiment, task=task)
        rows.append(
            {
                "task_id": task.task_id,
                "difficulty": task.difficulty,
                "category": task.category,
                **material,
            }
        )

    summary = summarize(rows)
    payload = {
        "config": args.config,
        "task_count": len(rows),
        "summary": summary,
        "tasks": rows,
    }
    text = json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    print(text, end="")

    allowed = {item for item in args.require_status if item}
    if allowed and any(row["task_material_status"] not in allowed for row in rows):
        raise SystemExit(2)


def summarize(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("task_material_status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


if __name__ == "__main__":
    main()
