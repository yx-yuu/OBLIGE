from __future__ import annotations

import json
import subprocess
from pathlib import Path

from edos.types import ExperimentConfig, TaskProgress, TaskSpec, WorkspaceSpec


def reference_score(task_progress: TaskProgress, failure_label: str | None) -> dict:
    candidate_build_success = bool(task_progress.last_compile_success)
    final_submission_seen = bool(task_progress.final_submission_seen)
    if failure_label in {"no_candidate", "agent_timeout", "step_limit"}:
        tests_passed_fraction = 0.0
        resolved = False
    elif candidate_build_success and final_submission_seen:
        tests_passed_fraction = 0.7
        resolved = False
    elif candidate_build_success:
        tests_passed_fraction = 0.45
        resolved = False
    else:
        tests_passed_fraction = 0.1
        resolved = False
    return {
        "resolved": resolved,
        "tests_passed_fraction": tests_passed_fraction,
        "tests_passed": int(round(tests_passed_fraction * 10)),
        "tests_total": 10,
        "candidate_build_success": candidate_build_success,
        "final_submission_seen": final_submission_seen,
        "score_status": "local_reference",
    }


def run_scoring_command(
    *,
    experiment: ExperimentConfig,
    task: TaskSpec,
    workspace: WorkspaceSpec,
    run_dir: str,
) -> dict:
    command = task.scorer_command or experiment.scoring_command
    if not command:
        return {
            "resolved": False,
            "tests_passed_fraction": None,
            "tests_passed": None,
            "tests_total": None,
            "candidate_build_success": None,
            "final_submission_seen": None,
            "score_status": "missing",
            "score_reason": "no_scoring_command_configured",
        }

    rendered = render_command(
        command,
        {
            "repo_root": str(Path.cwd()),
            "task_id": task.task_id,
            "workspace": workspace.workspace_path,
            "run_dir": run_dir,
            "gold_executable": workspace.gold_executable or "",
            "docs_path": workspace.docs_path or "",
        },
    )
    try:
        completed = subprocess.run(
            rendered,
            cwd=workspace.workspace_path,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=experiment.timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "resolved": False,
            "tests_passed_fraction": None,
            "tests_passed": None,
            "tests_total": None,
            "candidate_build_success": None,
            "final_submission_seen": None,
            "score_status": "error",
            "score_reason": "scorer_timeout",
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
        }
    except FileNotFoundError as exc:
        return {
            "resolved": False,
            "tests_passed_fraction": None,
            "tests_passed": None,
            "tests_total": None,
            "candidate_build_success": None,
            "final_submission_seen": None,
            "score_status": "error",
            "score_reason": f"scorer_not_found:{exc.filename}",
        }
    raw_path = Path(run_dir) / "programbench_score.raw.json"
    raw_path.write_text(
        json.dumps(
            {
                "command": rendered,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if completed.returncode != 0:
        return {
            "resolved": False,
            "tests_passed_fraction": None,
            "tests_passed": None,
            "tests_total": None,
            "candidate_build_success": None,
            "final_submission_seen": None,
            "score_status": "error",
            "score_reason": f"scorer_returncode:{completed.returncode}",
        }
    parsed = parse_score_output(completed.stdout)
    parsed.setdefault("score_status", "ok")
    return parsed


def parse_score_output(output: str) -> dict:
    text = output.strip()
    if not text:
        return {"score_status": "error", "score_reason": "empty_scorer_output"}
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return {
            "score_status": "error",
            "score_reason": "scorer_output_not_json",
            "raw_stdout_preview": text[:500],
        }
    tests_passed = raw.get("tests_passed")
    tests_total = raw.get("tests_total")
    fraction = raw.get("tests_passed_fraction")
    if fraction is None and tests_passed is not None and tests_total:
        fraction = float(tests_passed) / float(tests_total)
    return {
        "resolved": bool(raw.get("resolved", False)),
        "tests_passed_fraction": fraction,
        "tests_passed": tests_passed,
        "tests_total": tests_total,
        "candidate_build_success": raw.get("candidate_build_success"),
        "final_submission_seen": raw.get("final_submission_seen"),
        "score_status": raw.get("score_status", "ok"),
    }


def parse_programbench_eval_json(
    path: str | Path,
    *,
    tests_json: str | Path | None = None,
) -> dict:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    tests_metadata = None
    if tests_json is not None:
        tests_metadata = json.loads(Path(tests_json).read_text(encoding="utf-8"))
    return normalize_programbench_eval(raw, tests_metadata=tests_metadata)


def normalize_programbench_eval(raw: dict, *, tests_metadata: dict | None = None) -> dict:
    results = raw.get("test_results") or []
    raw_passed = sum(1 for item in results if item.get("status") == "passed")
    raw_total = len(results)
    error_code = raw.get("error_code")
    raw_branch_errors = raw.get("test_branch_errors") or {}
    active_branches: list[str] | None = None
    ignored_tests: set[str] = set()
    ignored_branches: set[str] = set()
    scoring_mode = "raw_eval_json"

    scored_results = results
    branch_errors = raw_branch_errors
    warnings = raw.get("warnings") or []
    test_branches = raw.get("test_branches") or []
    if tests_metadata is not None:
        branches = tests_metadata.get("branches") or {}
        active_branches = [
            name for name, info in branches.items() if not (info or {}).get("ignored")
        ]
        ignored_branches = {
            name for name, info in branches.items() if (info or {}).get("ignored")
        }
        ignored_tests = collect_ignored_programbench_tests(tests_metadata)
        active_branch_set = set(active_branches)
        scored_results = [
            item
            for item in results
            if item.get("branch") in active_branch_set
            and full_programbench_test_name(item) not in ignored_tests
        ]
        branch_errors = {
            branch: errors
            for branch, errors in raw_branch_errors.items()
            if branch in active_branch_set
        }
        test_branches = active_branches
        if ignored_branches:
            warnings = [
                warning
                for warning in warnings
                if not any(f"branch {branch}" in warning for branch in ignored_branches)
            ]
        scoring_mode = "official_tests_json"

    passed = sum(1 for item in scored_results if item.get("status") == "passed")
    total = len(scored_results)
    score = passed / total if total else 0.0
    resolved = bool(total and passed == total and not error_code and not branch_errors)
    return {
        "resolved": resolved,
        "tests_passed_fraction": score,
        "tests_passed": passed,
        "tests_total": total,
        "candidate_build_success": bool(raw.get("executable_hash")),
        "final_submission_seen": True,
        "score_status": "programbench_eval" if not error_code else "programbench_error",
        "programbench_error_code": error_code,
        "programbench_error_details": raw.get("error_details"),
        "programbench_test_branches": test_branches,
        "programbench_test_branch_errors": branch_errors,
        "programbench_n_system_errors": sum(
            1 for item in scored_results if item.get("status") == "system_error"
        ),
        "programbench_warnings": warnings,
        "programbench_executable_hash": raw.get("executable_hash"),
        "programbench_scoring_mode": scoring_mode,
        "programbench_raw_tests_passed": raw_passed,
        "programbench_raw_tests_total": raw_total,
        "programbench_raw_test_branch_errors": raw_branch_errors,
        "programbench_raw_test_branches": raw.get("test_branches") or [],
        "programbench_ignored_tests_count": len(ignored_tests),
        "programbench_ignored_branches": sorted(ignored_branches),
        "programbench_active_branches": active_branches,
    }


def collect_ignored_programbench_tests(tests_metadata: dict) -> set[str]:
    ignored: set[str] = set()
    for branch, info in (tests_metadata.get("branches") or {}).items():
        for item in (info or {}).get("ignored_tests") or []:
            name = item.get("name")
            if name:
                ignored.add(f"{branch}/{name}")
    return ignored


def full_programbench_test_name(result: dict) -> str:
    branch = result.get("branch") or ""
    name = result.get("name") or ""
    return f"{branch}/{name}" if branch else name


def render_command(command: list[str], values: dict[str, str]) -> list[str]:
    rendered: list[str] = []
    for part in command:
        current = part
        for key, value in values.items():
            current = current.replace("{" + key + "}", value)
        rendered.append(current)
    return rendered
