from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

from edos.programbench.preflight import (
    FAIL,
    format_report,
    programbench_uv_env,
    run_preflight,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--programbench-root", required=True)
    parser.add_argument("--source", required=True, help="Official ProgramBench run dir")
    parser.add_argument("--filter", default="")
    parser.add_argument("--slice", default="")
    parser.add_argument("--workers", default="1")
    parser.add_argument("--branch-workers", default="1")
    parser.add_argument("--docker-cpus", default="")
    parser.add_argument(
        "--docker-host",
        default="",
        help="Optional DOCKER_HOST value for ProgramBench/Docker, e.g. unix:///path/to/docker.sock.",
    )
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--output", default="")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--preflight-report", default="")
    args = parser.parse_args()

    programbench_root = Path(args.programbench_root).resolve()
    source = Path(args.source).resolve()
    output = Path(args.output).resolve() if args.output else None
    docker_host = args.docker_host or os.environ.get("EDOS_DOCKER_HOST", "")

    if not args.skip_preflight:
        report = run_preflight(
            programbench_root=programbench_root,
            source=source,
            filter_pattern=args.filter,
            require_docker=not args.summarize_only,
            docker_host=docker_host,
        )
        print(format_report(report))
        if args.preflight_report:
            report_path = Path(args.preflight_report)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        if report["status"] == FAIL:
            raise SystemExit(2)
        if args.preflight_only:
            return

    command = [
        "uv",
        "run",
        "programbench",
        "eval",
        str(source),
        "--workers",
        args.workers,
        "--branch-workers",
        args.branch_workers,
    ]
    if args.docker_cpus:
        command.extend(["--docker-cpus", args.docker_cpus])
    if args.filter:
        command.extend(["--filter", args.filter])
    if args.slice:
        command.extend(["--slice", args.slice])
    if args.summarize_only:
        command.append("--summarize-only")
    if args.force:
        command.append("--force")
    if output is not None:
        command.extend(["--output", str(output)])
    env = programbench_uv_env()
    if docker_host:
        env["DOCKER_HOST"] = docker_host

    completed = subprocess.run(
        command,
        cwd=programbench_root,
        env=env,
        text=True,
        check=False,
    )
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
