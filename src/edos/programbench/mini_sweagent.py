from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import Any

from edos.llm.openai_compatible import OpenAICompatibleProfile
from edos.programbench.docker import (
    FAIL,
    PASS,
    WARN,
    check_docker_requirements,
    trim_output,
)


def mini_sweagent_uv_env(
    *,
    docker_host: str = "",
    model_profile: OpenAICompatibleProfile | None = None,
    programbench_root: str | Path | None = None,
    use_local_venv: bool = False,
) -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("UV_CACHE_DIR", "/tmp/uv-cache")
    env.setdefault("UV_PYTHON_INSTALL_DIR", "/tmp/uv-python")
    repo_src = str(Path(__file__).resolve().parents[2])
    current_pythonpath = env.get("PYTHONPATH", "")
    pythonpath_parts = [part for part in current_pythonpath.split(os.pathsep) if part]
    if use_local_venv and programbench_root is not None:
        pythonpath_parts = [
            *local_programbench_pythonpath_parts(Path(programbench_root)),
            *pythonpath_parts,
        ]
    if repo_src not in pythonpath_parts:
        env["PYTHONPATH"] = os.pathsep.join([repo_src, *pythonpath_parts])
    elif pythonpath_parts:
        env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    if docker_host:
        env["DOCKER_HOST"] = docker_host
    if model_profile is not None:
        env = model_profile.env_for_subprocess(env)
    return env


def build_mini_sweagent_programbench_command(
    *,
    mini_sweagent_root: str | Path,
    programbench_root: str | Path,
    output: str | Path,
    model: str = "",
    filter_pattern: str = "",
    slice_spec: str = "",
    workers: int = 1,
    config_specs: list[str] | None = None,
    environment_class: str = "",
    model_class: str = "",
    redo_existing: bool = False,
    extra_config_specs: list[str] | None = None,
    execution_mode: str = "uv",
) -> list[str]:
    validate_execution_mode(execution_mode)
    config_specs = config_specs or ["programbench.yaml"]
    extra_config_specs = extra_config_specs or []
    if execution_mode == "local_venv":
        command = [
            str(local_mini_python(Path(mini_sweagent_root).resolve())),
            "-m",
            "minisweagent.run.benchmarks.programbench",
            "--output",
            str(Path(output).resolve()),
            "--workers",
            str(workers),
        ]
    else:
        command = [
            "uv",
            "run",
            "--with-editable",
            str(Path(programbench_root).resolve()),
            "-m",
            "minisweagent.run.benchmarks.programbench",
            "--output",
            str(Path(output).resolve()),
            "--workers",
            str(workers),
        ]
    if model:
        command.extend(["--model", model])
    if filter_pattern:
        command.extend(["--filter", filter_pattern])
    if slice_spec:
        command.extend(["--slice", slice_spec])
    for config in config_specs + extra_config_specs:
        command.extend(["--config", normalize_mini_sweagent_config_spec(config)])
    if environment_class:
        command.extend(["--environment-class", environment_class])
    if model_class:
        command.extend(["--model-class", model_class])
    if redo_existing:
        command.append("--redo-existing")
    return command


def validate_execution_mode(execution_mode: str) -> None:
    if execution_mode not in {"uv", "local_venv"}:
        raise ValueError(f"Unsupported mini-SWE-agent execution mode: {execution_mode}")


def local_mini_python(mini_root: Path) -> Path:
    return mini_root / ".venv" / "bin" / "python"


def local_programbench_pythonpath_parts(programbench_root: Path) -> list[str]:
    root = programbench_root.resolve()
    parts = [
        str(path.resolve())
        for path in sorted((root / ".venv" / "lib").glob("python*/site-packages"))
        if path.is_dir()
    ]
    src = root / "src"
    if src.exists():
        parts.append(str(src.resolve()))
    return parts


def normalize_mini_sweagent_config_spec(config: str) -> str:
    """Resolve local config files before mini-SWE-agent changes cwd."""
    if "=" in config:
        return config
    config_path = Path(config)
    if config_path.is_absolute():
        return str(config_path)
    if config_path.exists():
        return str(config_path.resolve())
    return config


def run_mini_sweagent_preflight(
    *,
    mini_sweagent_root: str | Path,
    programbench_root: str | Path,
    output: str | Path,
    require_docker: bool = True,
    docker_host: str = "",
    check_cli: bool = True,
    execution_mode: str = "uv",
) -> dict[str, Any]:
    validate_execution_mode(execution_mode)
    mini_root = Path(mini_sweagent_root)
    pb_root = Path(programbench_root)
    output_path = Path(output)
    checks: list[dict[str, str]] = []

    checks.append(_check_dir("mini_sweagent_root", mini_root))
    if mini_root.exists():
        checks.append(_check_file("mini_sweagent_pyproject", mini_root / "pyproject.toml"))
        checks.append(
            _check_file(
                "mini_sweagent_programbench_runner",
                mini_root / "src" / "minisweagent" / "run" / "benchmarks" / "programbench.py",
            )
        )
        checks.append(
            _check_file(
                "mini_sweagent_programbench_config",
                mini_root / "src" / "minisweagent" / "config" / "benchmarks" / "programbench.yaml",
            )
        )
        if execution_mode == "local_venv":
            checks.append(_check_file("mini_sweagent_local_python", local_mini_python(mini_root)))
    checks.append(_check_dir("programbench_root", pb_root))
    if pb_root.exists():
        checks.append(_check_file("programbench_pyproject", pb_root / "pyproject.toml"))
        if execution_mode == "local_venv":
            checks.append(_check_programbench_local_env(pb_root))

    checks.append(_check_output_parent(output_path))
    checks.append(_check_architecture())

    if check_cli and mini_root.exists() and pb_root.exists():
        checks.append(
            _check_mini_programbench_cli(
                mini_root,
                pb_root,
                docker_host=docker_host,
                execution_mode=execution_mode,
            )
        )

    checks.extend(
        check_docker_requirements(
            require_docker=require_docker,
            docker_executable="docker",
            docker_host=docker_host,
        )
    )

    status = FAIL if any(item["status"] == FAIL for item in checks) else WARN
    if all(item["status"] == PASS for item in checks):
        status = PASS
    return {
        "status": status,
        "mini_sweagent_root": str(mini_root),
        "programbench_root": str(pb_root),
        "output": str(output_path),
        "docker_host": docker_host,
        "execution_mode": execution_mode,
        "checks": checks,
    }


def format_mini_sweagent_preflight(report: dict[str, Any]) -> str:
    lines = [f"mini-SWE-agent ProgramBench preflight status: {report['status']}"]
    for item in report["checks"]:
        lines.append(f"- [{item['status']}] {item['name']}: {item['detail']}")
    return "\n".join(lines)


def _check_dir(name: str, path: Path) -> dict[str, str]:
    if not path.exists():
        return {"name": name, "status": FAIL, "detail": f"Path does not exist: {path}"}
    if not path.is_dir():
        return {"name": name, "status": FAIL, "detail": f"Path is not a directory: {path}"}
    return {"name": name, "status": PASS, "detail": f"Path exists: {path}"}


def _check_file(name: str, path: Path) -> dict[str, str]:
    if not path.exists():
        return {"name": name, "status": FAIL, "detail": f"File does not exist: {path}"}
    if not path.is_file():
        return {"name": name, "status": FAIL, "detail": f"Path is not a file: {path}"}
    return {"name": name, "status": PASS, "detail": f"File exists: {path}"}


def _check_output_parent(path: Path) -> dict[str, str]:
    parent = path.parent if path.parent != Path("") else Path(".")
    if not parent.exists():
        return {"name": "output_parent", "status": FAIL, "detail": f"Output parent does not exist: {parent}"}
    if not os.access(parent, os.W_OK):
        return {"name": "output_parent", "status": FAIL, "detail": f"Output parent is not writable: {parent}"}
    return {"name": "output_parent", "status": PASS, "detail": f"Output parent is writable: {parent}"}


def _check_architecture() -> dict[str, str]:
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        return {
            "name": "host_architecture",
            "status": PASS,
            "detail": f"Host architecture is {platform.machine()}, compatible with ProgramBench linux/amd64 images.",
        }
    return {
        "name": "host_architecture",
        "status": WARN,
        "detail": f"Host architecture is {platform.machine()}; ProgramBench images require linux/amd64.",
    }


def _check_programbench_local_env(pb_root: Path) -> dict[str, str]:
    site_packages = local_programbench_pythonpath_parts(pb_root)
    if not site_packages:
        return {
            "name": "programbench_local_env",
            "status": FAIL,
            "detail": f"No ProgramBench local environment found under {pb_root / '.venv'}.",
        }
    return {
        "name": "programbench_local_env",
        "status": PASS,
        "detail": "ProgramBench local environment is available.",
    }


def _check_mini_programbench_cli(
    mini_root: Path,
    pb_root: Path,
    *,
    docker_host: str = "",
    execution_mode: str = "uv",
) -> dict[str, str]:
    if execution_mode == "local_venv":
        command = [
            str(local_mini_python(mini_root)),
            "-m",
            "minisweagent.run.benchmarks.programbench",
            "--help",
        ]
    else:
        command = [
            "uv",
            "run",
            "--with-editable",
            str(pb_root.resolve()),
            "-m",
            "minisweagent.run.benchmarks.programbench",
            "--help",
        ]
    try:
        result = subprocess.run(
            command,
            cwd=mini_root,
            env=mini_sweagent_uv_env(
                docker_host=docker_host,
                programbench_root=pb_root,
                use_local_venv=execution_mode == "local_venv",
            ),
            text=True,
            capture_output=True,
            timeout=180,
            check=False,
        )
    except FileNotFoundError:
        return {"name": "mini_sweagent_programbench_cli", "status": FAIL, "detail": "uv executable not found."}
    except subprocess.TimeoutExpired:
        return {
            "name": "mini_sweagent_programbench_cli",
            "status": FAIL,
            "detail": "mini-SWE-agent ProgramBench --help timed out after 180 seconds.",
        }
    if result.returncode != 0:
        return {
            "name": "mini_sweagent_programbench_cli",
            "status": FAIL,
            "detail": trim_output(result.stderr or result.stdout),
        }
    return {
        "name": "mini_sweagent_programbench_cli",
        "status": PASS,
        "detail": "mini-SWE-agent ProgramBench runner help completed successfully.",
    }

