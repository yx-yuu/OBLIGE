from __future__ import annotations

import os
import platform
import re
import subprocess
import tarfile
from pathlib import Path
from typing import Any

from edos.programbench.docker import (
    FAIL,
    PASS,
    WARN,
    check_docker_requirements,
    trim_output,
)

_trim_output = trim_output


def programbench_uv_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("UV_CACHE_DIR", "/tmp/uv-cache")
    env.setdefault("UV_PYTHON_INSTALL_DIR", "/tmp/uv-python")
    return env


def run_preflight(
    *,
    programbench_root: str | Path,
    source: str | Path,
    filter_pattern: str = "",
    require_docker: bool = True,
    check_cli: bool = True,
    docker_executable: str = "docker",
    docker_host: str = "",
) -> dict[str, Any]:
    root = Path(programbench_root)
    source_path = Path(source)
    checks: list[dict[str, Any]] = []

    checks.append(_check_path("programbench_root", root, must_be_dir=True))
    checks.append(_check_path("source", source_path, must_be_dir=True))
    if root.exists():
        checks.append(
            _check_path(
                "programbench_pyproject",
                root / "pyproject.toml",
                must_be_dir=False,
                detail_on_pass="ProgramBench pyproject.toml exists.",
            )
        )

    if source_path.exists():
        checks.extend(_check_submissions(source_path, filter_pattern))

    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        checks.append(
            {
                "name": "host_architecture",
                "status": PASS,
                "detail": f"Host architecture is {platform.machine()}, compatible with ProgramBench linux/amd64 images.",
            }
        )
    else:
        checks.append(
            {
                "name": "host_architecture",
                "status": WARN,
                "detail": (
                    f"Host architecture is {platform.machine()}; ProgramBench official images are linux/amd64. "
                    "Native evaluation may be unavailable or slow under emulation."
                ),
            }
        )

    if check_cli and root.exists():
        checks.append(_check_programbench_cli(root))

    checks.extend(
        check_docker_requirements(
            require_docker=require_docker,
            docker_executable=docker_executable,
            docker_host=docker_host,
        )
    )

    status = FAIL if any(item["status"] == FAIL for item in checks) else WARN
    if all(item["status"] == PASS for item in checks):
        status = PASS
    return {
        "status": status,
        "programbench_root": str(root),
        "source": str(source_path),
        "filter": filter_pattern,
        "docker_host": docker_host,
        "checks": checks,
    }


def format_report(report: dict[str, Any]) -> str:
    lines = [f"ProgramBench preflight status: {report['status']}"]
    for item in report["checks"]:
        lines.append(f"- [{item['status']}] {item['name']}: {item['detail']}")
    return "\n".join(lines)


def _check_path(
    name: str,
    path: Path,
    *,
    must_be_dir: bool,
    detail_on_pass: str | None = None,
) -> dict[str, str]:
    if not path.exists():
        return {"name": name, "status": FAIL, "detail": f"Path does not exist: {path}"}
    if must_be_dir and not path.is_dir():
        return {"name": name, "status": FAIL, "detail": f"Path is not a directory: {path}"}
    if not must_be_dir and not path.is_file():
        return {"name": name, "status": FAIL, "detail": f"Path is not a file: {path}"}
    return {"name": name, "status": PASS, "detail": detail_on_pass or f"Path exists: {path}"}


def _check_submissions(source: Path, filter_pattern: str) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    try:
        pattern = re.compile(filter_pattern) if filter_pattern else None
    except re.error as exc:
        return [
            {
                "name": "instance_filter",
                "status": FAIL,
                "detail": f"Invalid regex filter {filter_pattern!r}: {exc}",
            }
        ]

    archives = []
    for archive in sorted(source.glob("*/submission.tar.gz")):
        instance_id = archive.parent.name
        if pattern is not None and not pattern.search(instance_id):
            continue
        archives.append(archive)

    if not archives:
        checks.append(
            {
                "name": "submission_archives",
                "status": FAIL,
                "detail": (
                    f"No <instance_id>/submission.tar.gz archives found under {source}"
                    + (f" after applying filter {filter_pattern!r}." if filter_pattern else ".")
                ),
            }
        )
        return checks

    checks.append(
        {
            "name": "submission_archives",
            "status": PASS,
            "detail": f"Found {len(archives)} submission archive(s).",
            "archives": [str(item) for item in archives],
        }
    )
    for archive in archives:
        checks.append(_check_submission_archive(archive))
    return checks


def _check_submission_archive(path: Path) -> dict[str, str]:
    try:
        with tarfile.open(path, "r:gz") as tar:
            names = tar.getnames()
    except (tarfile.TarError, OSError) as exc:
        return {
            "name": f"submission_archive:{path.parent.name}",
            "status": FAIL,
            "detail": f"Cannot read tar.gz archive {path}: {exc}",
        }
    unsafe = [name for name in names if _is_unsafe_tar_member(name)]
    if unsafe:
        return {
            "name": f"submission_archive:{path.parent.name}",
            "status": FAIL,
            "detail": f"Archive contains unsafe member path(s): {unsafe[:3]}",
        }
    normalized = {name.removeprefix("./") for name in names}
    if "compile.sh" not in normalized:
        return {
            "name": f"submission_archive:{path.parent.name}",
            "status": FAIL,
            "detail": "Archive does not contain top-level compile.sh required by ProgramBench.",
        }
    return {
        "name": f"submission_archive:{path.parent.name}",
        "status": PASS,
        "detail": f"Archive is readable and contains top-level compile.sh ({len(names)} member(s)).",
    }


def _is_unsafe_tar_member(name: str) -> bool:
    parts = Path(name).parts
    return name.startswith("/") or ".." in parts


def _check_programbench_cli(root: Path) -> dict[str, str]:
    command = ["uv", "run", "programbench", "--help"]
    try:
        result = subprocess.run(
            command,
            cwd=root,
            env=programbench_uv_env(),
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
    except FileNotFoundError:
        return {"name": "programbench_cli", "status": FAIL, "detail": "uv executable not found."}
    except subprocess.TimeoutExpired:
        return {
            "name": "programbench_cli",
            "status": FAIL,
            "detail": "uv run programbench --help timed out after 120 seconds.",
        }
    if result.returncode != 0:
        return {
            "name": "programbench_cli",
            "status": FAIL,
            "detail": trim_output(result.stderr or result.stdout),
        }
    return {
        "name": "programbench_cli",
        "status": PASS,
        "detail": "uv run programbench --help completed successfully.",
    }
