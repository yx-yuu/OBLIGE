from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path

from edos.llm.openai_compatible import load_openai_compatible_profile
from edos.programbench.mini_sweagent import (
    FAIL,
    build_mini_sweagent_programbench_command,
    format_mini_sweagent_preflight,
    mini_sweagent_uv_env,
    run_mini_sweagent_preflight,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mini-sweagent-root", required=True)
    parser.add_argument("--programbench-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--model",
        default="",
        help="Model name. Optional when --model-config is set; overrides the model in that JSON.",
    )
    parser.add_argument(
        "--model-config",
        default="",
        help="OpenAI-compatible model profile JSON, e.g. configs/models/openai_compatible.json.",
    )
    parser.add_argument("--filter", default="")
    parser.add_argument("--slice", default="")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--config",
        action="append",
        default=[],
        help="mini-SWE-agent config specs. Defaults to programbench.yaml when omitted.",
    )
    parser.add_argument(
        "--extra-config",
        action="append",
        default=[],
        help="Additional mini-SWE-agent key=value config specs appended after --config.",
    )
    parser.add_argument("--environment-class", default="")
    parser.add_argument("--model-class", default="")
    parser.add_argument(
        "--execution-mode",
        choices=["uv", "local_venv"],
        default="uv",
        help=(
            "How to launch mini-SWE-agent. local_venv reuses the existing "
            "mini-SWE-agent and ProgramBench .venv directories."
        ),
    )
    parser.add_argument("--redo-existing", action="store_true")
    parser.add_argument(
        "--docker-host",
        default="",
        help="Optional DOCKER_HOST value, e.g. unix:///path/to/docker.sock.",
    )
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--preflight-report", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    mini_root = Path(args.mini_sweagent_root).resolve()
    programbench_root = Path(args.programbench_root).resolve()
    output = Path(args.output).resolve()
    docker_host = args.docker_host or os.environ.get("EDOS_DOCKER_HOST", "")
    config_specs = args.config or ["programbench.yaml"]
    model_profile = (
        load_openai_compatible_profile(args.model_config)
        if args.model_config
        else None
    )
    if model_profile is not None and args.model:
        model_profile = replace(model_profile, model=args.model)
    model_name = args.model or (model_profile.model if model_profile is not None else "")
    if not model_name:
        parser.error("Either --model or --model-config is required.")
    profile_config_specs = (
        model_profile.mini_sweagent_config_specs() if model_profile is not None else []
    )
    extra_config_specs = profile_config_specs + args.extra_config
    model_class = args.model_class or (
        model_profile.model_class if model_profile is not None else ""
    )
    if model_profile is not None:
        write_model_profile_snapshot(output, model_profile)
        print(
            "Using model profile "
            f"{model_profile.profile_name} ({model_profile.stable_hash()[:12]})"
        )

    if not args.skip_preflight:
        report = run_mini_sweagent_preflight(
            mini_sweagent_root=mini_root,
            programbench_root=programbench_root,
            output=output,
            require_docker=True,
            docker_host=docker_host,
            execution_mode=args.execution_mode,
        )
        print(format_mini_sweagent_preflight(report))
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

    command = build_mini_sweagent_programbench_command(
        mini_sweagent_root=mini_root,
        programbench_root=programbench_root,
        output=output,
        model=model_name,
        filter_pattern=args.filter,
        slice_spec=args.slice,
        workers=args.workers,
        config_specs=config_specs,
        environment_class=args.environment_class,
        model_class=model_class,
        redo_existing=args.redo_existing,
        extra_config_specs=extra_config_specs,
        execution_mode=args.execution_mode,
    )
    print(" ".join(command))
    if args.dry_run:
        return
    completed = subprocess.run(
        command,
        cwd=mini_root,
        env=mini_sweagent_uv_env(
            docker_host=docker_host,
            model_profile=model_profile,
            programbench_root=programbench_root,
            use_local_venv=args.execution_mode == "local_venv",
        ),
        text=True,
        check=False,
    )
    raise SystemExit(completed.returncode)


def write_model_profile_snapshot(output: Path, model_profile) -> None:
    output.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "profile": model_profile.redacted_snapshot(),
        "profile_hash": model_profile.stable_hash(),
    }
    (output / "model_profile.redacted.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
