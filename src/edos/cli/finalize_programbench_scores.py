from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from edos.analysis.aggregate import aggregate
from edos.cli.ingest_programbench_eval import ingest_programbench_eval
from edos.programbench.preflight import (
    FAIL,
    format_report,
    programbench_uv_env,
    run_preflight,
)


def finalize_programbench_scores(
    *,
    run_dir: str | Path,
    programbench_root: str | Path,
    conditions: list[str] | None = None,
    instance_filter: str = "",
    slice_expr: str = "",
    workers: str = "1",
    branch_workers: str = "1",
    docker_cpus: str = "",
    docker_host: str = "",
    preflight_only: bool = False,
    skip_preflight: bool = False,
    skip_eval: bool = False,
    summarize_only: bool = False,
    force: bool = False,
    allow_raw_scoring: bool = False,
    keep_existing_scores_for_missing_eval: bool = False,
    no_aggregate: bool = False,
    continue_on_error: bool = False,
) -> dict[str, Any]:
    run_path = Path(run_dir)
    pb_root = Path(programbench_root).resolve()
    eval_root = run_path / "programbench_runs"
    selected_sources = discover_condition_sources(eval_root, conditions)
    if not selected_sources:
        raise ValueError(
            f"No ProgramBench condition directories found under {eval_root}; "
            "pass --condition explicitly after exporting submissions."
        )
    finalize_dir = run_path / "programbench_finalize"
    finalize_dir.mkdir(parents=True, exist_ok=True)

    steps: list[dict[str, Any]] = []
    failed = False
    if skip_eval and not preflight_only:
        skip_preflight = True

    for source_info in selected_sources:
        condition = source_info["condition"]
        source = Path(source_info["source"])
        step = {
            "condition": condition,
            "repeat_label": source_info.get("repeat_label", ""),
            "source": str(source),
            "preflight": None,
            "eval": None,
        }
        step_name = safe_condition_step_name(condition, step["repeat_label"])
        if not skip_preflight:
            report = run_preflight(
                programbench_root=pb_root,
                source=source,
                filter_pattern=instance_filter,
                require_docker=not summarize_only and not skip_eval,
                docker_host=docker_host,
            )
            report_path = finalize_dir / f"preflight_{step_name}.json"
            report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            step["preflight"] = {
                "status": report["status"],
                "report": str(report_path),
            }
            if report["status"] == FAIL:
                failed = True
                step["status"] = "preflight_failed"
                steps.append(step)
                if not continue_on_error:
                    break
                continue

        if preflight_only:
            step["status"] = "preflight_only"
            steps.append(step)
            continue
        if skip_eval:
            step["status"] = "eval_skipped"
            steps.append(step)
            continue

        command = build_programbench_eval_command(
            source=source,
            filter_pattern=instance_filter,
            slice_expr=slice_expr,
            workers=workers,
            branch_workers=branch_workers,
            docker_cpus=docker_cpus,
            summarize_only=summarize_only,
            force=force,
        )
        stdout_path = finalize_dir / f"eval_{step_name}.stdout.txt"
        stderr_path = finalize_dir / f"eval_{step_name}.stderr.txt"
        completed = run_programbench_eval_command(
            command=command,
            programbench_root=pb_root,
            docker_host=docker_host,
        )
        stdout_path.write_text(completed.stdout or "", encoding="utf-8")
        stderr_path.write_text(completed.stderr or "", encoding="utf-8")
        step["eval"] = {
            "command": command,
            "returncode": completed.returncode,
            "stdout": str(stdout_path),
            "stderr": str(stderr_path),
        }
        if completed.returncode != 0:
            failed = True
            step["status"] = "eval_failed"
            steps.append(step)
            if not continue_on_error:
                break
            continue
        step["status"] = "eval_completed"
        steps.append(step)

    ingest_summary: dict[str, Any] | None = None
    aggregate_paths: dict[str, str] | None = None
    if not preflight_only and (continue_on_error or not failed):
        ingest_summary = ingest_programbench_eval(
            run_dir=run_path,
            programbench_root=pb_root if not allow_raw_scoring else None,
            eval_root=eval_root,
            allow_raw_scoring=allow_raw_scoring,
            mark_missing=not keep_existing_scores_for_missing_eval,
            conditions=conditions or [item["condition"] for item in selected_sources],
            instance_filter=instance_filter,
        )
        if not no_aggregate:
            aggregate_paths = {
                name: str(path) for name, path in aggregate(run_path).items()
            }

    status = "failed" if failed else "ok"
    if preflight_only and failed:
        status = "preflight_failed"
    elif preflight_only:
        status = "preflight_ok"
    manifest = {
        "status": status,
        "run_dir": str(run_path),
        "programbench_root": str(pb_root),
        "conditions": sorted(dict.fromkeys(item["condition"] for item in selected_sources)),
        "condition_sources": selected_sources,
        "filter": instance_filter,
        "slice": slice_expr,
        "workers": workers,
        "branch_workers": branch_workers,
        "docker_cpus": docker_cpus,
        "docker_host": docker_host,
        "preflight_only": preflight_only,
        "skip_preflight": skip_preflight,
        "skip_eval": skip_eval,
        "summarize_only": summarize_only,
        "force": force,
        "allow_raw_scoring": allow_raw_scoring,
        "mark_missing_eval": not keep_existing_scores_for_missing_eval,
        "steps": steps,
        "ingest": ingest_summary,
        "aggregate": aggregate_paths,
    }
    manifest_path = finalize_dir / "programbench_finalize_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def discover_condition_sources(
    eval_root: str | Path,
    requested: list[str] | None = None,
) -> list[dict[str, str]]:
    root = Path(eval_root)
    if not root.exists():
        return []
    requested_set = set(requested or [])
    sources: list[dict[str, str]] = []
    direct_condition_names = {path.name for path in root.iterdir() if path.is_dir()}
    for path in sorted(root.iterdir()):
        if not path.is_dir():
            continue
        if path.name.startswith("rep") and path.name not in requested_set:
            for condition_dir in sorted(path.iterdir()):
                if not condition_dir.is_dir():
                    continue
                if requested_set and condition_dir.name not in requested_set:
                    continue
                sources.append(
                    {
                        "condition": condition_dir.name,
                        "repeat_label": path.name,
                        "source": str(condition_dir),
                    }
                )
            continue
        if path.name in direct_condition_names and (
            not requested_set or path.name in requested_set
        ):
            sources.append(
                {
                    "condition": path.name,
                    "repeat_label": "",
                    "source": str(path),
                }
            )
    return sources


def discover_conditions(
    eval_root: str | Path,
    requested: list[str] | None = None,
) -> list[str]:
    return sorted(
        dict.fromkeys(
            item["condition"]
            for item in discover_condition_sources(eval_root, requested)
        )
    )


def build_programbench_eval_command(
    *,
    source: str | Path,
    filter_pattern: str = "",
    slice_expr: str = "",
    workers: str = "1",
    branch_workers: str = "1",
    docker_cpus: str = "",
    summarize_only: bool = False,
    force: bool = False,
) -> list[str]:
    command = [
        "uv",
        "run",
        "programbench",
        "eval",
        str(Path(source).resolve()),
        "--workers",
        workers,
        "--branch-workers",
        branch_workers,
    ]
    if docker_cpus:
        command.extend(["--docker-cpus", docker_cpus])
    if filter_pattern:
        command.extend(["--filter", filter_pattern])
    if slice_expr:
        command.extend(["--slice", slice_expr])
    if summarize_only:
        command.append("--summarize-only")
    if force:
        command.append("--force")
    return command


def run_programbench_eval_command(
    *,
    command: list[str],
    programbench_root: str | Path,
    docker_host: str = "",
) -> subprocess.CompletedProcess[str]:
    env = programbench_uv_env()
    if docker_host:
        env["DOCKER_HOST"] = docker_host
    return subprocess.run(
        command,
        cwd=Path(programbench_root),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "condition"


def safe_condition_step_name(condition: str, repeat_label: str = "") -> str:
    if repeat_label:
        return safe_filename(f"{repeat_label}_{condition}")
    return safe_filename(condition)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--programbench-root", required=True)
    parser.add_argument(
        "--condition",
        action="append",
        default=[],
        help="Condition to finalize. Defaults to every directory under programbench_runs.",
    )
    parser.add_argument("--filter", default="", help="Regex filter for ProgramBench instance ids.")
    parser.add_argument("--slice", default="")
    parser.add_argument("--workers", default="1")
    parser.add_argument("--branch-workers", default="1")
    parser.add_argument("--docker-cpus", default="")
    parser.add_argument("--docker-host", default="")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--skip-eval", action="store_true")
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--allow-raw-scoring",
        action="store_true",
        help="Debug only. Do not use raw eval-json scoring for paper tables.",
    )
    parser.add_argument(
        "--keep-existing-scores-for-missing-eval",
        action="store_true",
        help=(
            "Do not overwrite selected runs without eval JSON. The default marks "
            "them as missing_programbench_eval to protect aggregate tables."
        ),
    )
    parser.add_argument("--no-aggregate", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    args = parser.parse_args()
    docker_host = args.docker_host or os.environ.get("EDOS_DOCKER_HOST", "")

    try:
        manifest = finalize_programbench_scores(
            run_dir=args.run_dir,
            programbench_root=args.programbench_root,
            conditions=args.condition,
            instance_filter=args.filter,
            slice_expr=args.slice,
            workers=args.workers,
            branch_workers=args.branch_workers,
            docker_cpus=args.docker_cpus,
            docker_host=docker_host,
            preflight_only=args.preflight_only,
            skip_preflight=args.skip_preflight,
            skip_eval=args.skip_eval,
            summarize_only=args.summarize_only,
            force=args.force,
            allow_raw_scoring=args.allow_raw_scoring,
            keep_existing_scores_for_missing_eval=args.keep_existing_scores_for_missing_eval,
            no_aggregate=args.no_aggregate,
            continue_on_error=args.continue_on_error,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"ProgramBench finalize failed: {exc}")
        raise SystemExit(2) from exc

    for step in manifest["steps"]:
        preflight = step.get("preflight") or {}
        if preflight:
            print(format_report(json.loads(Path(preflight["report"]).read_text(encoding="utf-8"))))
        eval_result = step.get("eval") or {}
        if eval_result:
            print(
                f"ProgramBench eval {step['condition']}: "
                f"returncode={eval_result['returncode']} "
                f"stdout={eval_result['stdout']} stderr={eval_result['stderr']}"
            )
        else:
            print(f"ProgramBench eval {step['condition']}: {step['status']}")
    if manifest.get("ingest"):
        ingest = manifest["ingest"]
        print(
            f"Imported official scores: updated={ingest['updated']} "
            f"missing_eval={ingest['missing_eval']} "
            f"marked_missing_eval={ingest['marked_missing_eval']} "
            f"missing_tests_json={ingest['missing_tests_json']} "
            f"skipped={ingest['skipped']}"
        )
    if manifest.get("aggregate"):
        for name, path in manifest["aggregate"].items():
            print(f"{name}: {path}")
    print(f"Manifest: {manifest['manifest_path']}")
    if manifest["status"] in {"failed", "preflight_failed"}:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
