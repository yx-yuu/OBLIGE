from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from edos.config import load_experiment_config
from edos.programbench.docker import (
    FAIL,
    check_docker_requirements,
    format_docker_checks,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="")
    parser.add_argument("--docker-executable", default="")
    parser.add_argument("--docker-host", default="")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    docker_executable = args.docker_executable or "docker"
    docker_host = args.docker_host or os.environ.get("EDOS_DOCKER_HOST", "")
    config_path = args.config
    if config_path:
        config = load_experiment_config(config_path)
        docker_executable = args.docker_executable or config.programbench_docker_executable
        docker_host = (
            args.docker_host
            or os.environ.get("EDOS_DOCKER_HOST", "")
            or config.programbench_docker_host
        )

    checks = check_docker_requirements(
        require_docker=True,
        docker_executable=docker_executable,
        docker_host=docker_host,
    )
    payload = {
        "status": FAIL if any(check["status"] == FAIL for check in checks) else "pass",
        "docker_executable": docker_executable,
        "docker_host": docker_host,
        "checks": checks,
    }
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print(f"Docker preflight status: {payload['status']}")
    print(format_docker_checks(checks))
    if payload["status"] == FAIL:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
