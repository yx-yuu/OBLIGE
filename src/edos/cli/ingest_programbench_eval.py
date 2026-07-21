from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from edos.programbench.scoring import parse_programbench_eval_json


def ingest_programbench_eval(
    *,
    run_dir: str | Path,
    programbench_root: str | Path | None = None,
    eval_root: str | Path | None = None,
    allow_raw_scoring: bool = False,
    mark_missing: bool = False,
    conditions: list[str] | None = None,
    instance_filter: str = "",
) -> dict[str, Any]:
    run_path = Path(run_dir)
    eval_path = Path(eval_root) if eval_root else run_path / "programbench_runs"
    pb_root = Path(programbench_root) if programbench_root else None
    if pb_root is None and not allow_raw_scoring:
        raise ValueError(
            "programbench_root is required unless allow_raw_scoring is set; "
            "raw eval-json counts do not match ProgramBench official scoring."
        )

    condition_set = set(conditions or [])
    pattern = re.compile(instance_filter) if instance_filter else None
    updated = 0
    missing = 0
    marked_missing = 0
    missing_tests_json = 0
    skipped = 0
    for metadata_path in sorted(run_path.glob("*/metadata.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        condition = metadata.get("condition", "")
        instance_id = metadata.get("task_id", "")
        if condition_set and condition not in condition_set:
            skipped += 1
            continue
        if pattern is not None and not pattern.search(instance_id):
            skipped += 1
            continue
        eval_json = expected_eval_json_path(
            eval_path=eval_path,
            condition=condition,
            instance_id=instance_id,
            repeat_label=str(metadata.get("repeat_label") or ""),
        )
        if not eval_json.exists():
            missing += 1
            if mark_missing:
                write_missing_programbench_eval_score(
                    run_dir=metadata_path.parent,
                    expected_eval_json=eval_json,
                )
                marked_missing += 1
            continue
        tests_json = (
            programbench_tests_json_path(pb_root, instance_id)
            if pb_root is not None
            else None
        )
        if tests_json is not None and not tests_json.exists():
            missing_tests_json += 1
            if not allow_raw_scoring:
                raise FileNotFoundError(f"ProgramBench tests.json not found: {tests_json}")
            tests_json = None
        score = parse_programbench_eval_json(eval_json, tests_json=tests_json)
        score["score_source"] = str(eval_json)
        if tests_json is not None:
            score["programbench_tests_json"] = str(tests_json)
        (metadata_path.parent / "programbench_score.json").write_text(
            json.dumps(score, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        updated += 1
    return {
        "updated": updated,
        "missing_eval": missing,
        "marked_missing_eval": marked_missing,
        "missing_tests_json": missing_tests_json,
        "skipped": skipped,
        "eval_root": str(eval_path),
    }


def write_missing_programbench_eval_score(
    *,
    run_dir: str | Path,
    expected_eval_json: str | Path,
) -> None:
    run_path = Path(run_dir)
    previous_score_path = run_path / "programbench_score.json"
    previous_score: dict[str, Any] = {}
    if previous_score_path.exists():
        previous_score = json.loads(previous_score_path.read_text(encoding="utf-8"))
    score = {
        "resolved": False,
        "tests_passed_fraction": None,
        "tests_passed": None,
        "tests_total": None,
        "candidate_build_success": previous_score.get("candidate_build_success"),
        "final_submission_seen": previous_score.get("final_submission_seen"),
        "score_status": "missing_programbench_eval",
        "score_reason": "official ProgramBench eval JSON was not found",
        "score_source": "",
        "expected_score_source": str(expected_eval_json),
        "programbench_scoring_mode": "missing_official_eval",
    }
    previous_score_path.write_text(
        json.dumps(score, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def expected_eval_json_path(
    *,
    eval_path: str | Path,
    condition: str,
    instance_id: str,
    repeat_label: str = "",
) -> Path:
    root = Path(eval_path)
    candidates = []
    if repeat_label:
        candidates.append(
            root / repeat_label / condition / instance_id / f"{instance_id}.eval.json"
        )
    candidates.append(root / condition / instance_id / f"{instance_id}.eval.json")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument(
        "--programbench-root",
        default="",
        help=(
            "ProgramBench repository root. Required by default so imported scores "
            "match programbench info semantics by filtering inactive branches and "
            "ignored tests from tests.json."
        ),
    )
    parser.add_argument(
        "--eval-root",
        default="",
        help=(
            "Directory containing <condition>/<instance_id>/<instance_id>.eval.json. "
            "Defaults to <run-dir>/programbench_runs."
        ),
    )
    parser.add_argument(
        "--allow-raw-scoring",
        action="store_true",
        help=(
            "Import raw eval-json counts without tests.json filtering. Use only for "
            "debugging; these scores are not ProgramBench official scores."
        ),
    )
    parser.add_argument(
        "--mark-missing",
        action="store_true",
        help=(
            "Overwrite runs without eval JSON as missing_programbench_eval so later "
            "aggregation cannot mistake local reference scores for official scores."
        ),
    )
    parser.add_argument(
        "--condition",
        action="append",
        default=[],
        help="Only import scores for this condition. Can be passed more than once.",
    )
    parser.add_argument(
        "--filter",
        default="",
        help="Only import scores for task ids matching this regex.",
    )
    args = parser.parse_args()

    if not args.programbench_root and not args.allow_raw_scoring:
        parser.error(
            "--programbench-root is required unless --allow-raw-scoring is set; "
            "raw eval-json counts do not match ProgramBench official scoring."
        )
    summary = ingest_programbench_eval(
        run_dir=args.run_dir,
        programbench_root=args.programbench_root or None,
        eval_root=args.eval_root or None,
        allow_raw_scoring=args.allow_raw_scoring,
        mark_missing=args.mark_missing,
        conditions=args.condition,
        instance_filter=args.filter,
    )
    print(
        f"Updated {summary['updated']} run score files from {summary['eval_root']}; "
        f"missing_eval={summary['missing_eval']}; "
        f"marked_missing_eval={summary['marked_missing_eval']}; "
        f"missing_tests_json={summary['missing_tests_json']}; "
        f"skipped={summary['skipped']}"
    )


def programbench_tests_json_path(programbench_root: Path, instance_id: str) -> Path:
    return (
        programbench_root
        / "src"
        / "programbench"
        / "data"
        / "tasks"
        / instance_id
        / "tests.json"
    )


if __name__ == "__main__":
    main()
