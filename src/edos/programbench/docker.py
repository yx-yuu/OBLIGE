from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


PASS = "pass"
WARN = "warn"
FAIL = "fail"

DOCKER_DESKTOP_WSL_SOCKET = Path(
    "/mnt/wsl/docker-desktop/shared-sockets/guest-services/docker.proxy.sock"
)


def docker_env(*, docker_host: str = "") -> dict[str, str]:
    env = dict(os.environ)
    if docker_host:
        env["DOCKER_HOST"] = docker_host
    return env


def check_docker_requirements(
    *,
    require_docker: bool = True,
    docker_executable: str = "docker",
    docker_host: str = "",
    timeout_seconds: int = 30,
) -> list[dict[str, Any]]:
    if not require_docker:
        return [
            {
                "name": "docker_daemon",
                "status": WARN,
                "detail": "Docker daemon check skipped because this invocation does not require Docker.",
            }
        ]

    cli = check_docker_cli(docker_executable)
    checks = [cli]
    if cli["status"] == PASS:
        checks.append(
            check_docker_daemon(
                docker_executable,
                docker_host=docker_host,
                timeout_seconds=timeout_seconds,
            )
        )
    return checks


def check_docker_cli(docker_executable: str = "docker") -> dict[str, str]:
    docker_path = shutil.which(docker_executable)
    if docker_path is None:
        detail = f"Docker executable not found: {docker_executable}."
        return {
            "name": "docker_cli",
            "status": FAIL,
            "detail": add_docker_hint(detail, docker_host=""),
        }
    return {
        "name": "docker_cli",
        "status": PASS,
        "detail": f"Docker executable found at {docker_path}.",
    }


def check_docker_daemon(
    docker_executable: str = "docker",
    *,
    docker_host: str = "",
    timeout_seconds: int = 30,
) -> dict[str, str]:
    try:
        result = subprocess.run(
            [docker_executable, "ps"],
            env=docker_env(docker_host=docker_host),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError:
        detail = "Docker executable not found."
        return {
            "name": "docker_daemon",
            "status": FAIL,
            "detail": add_docker_hint(detail, docker_host=docker_host),
        }
    except subprocess.TimeoutExpired:
        detail = f"docker ps timed out after {timeout_seconds} seconds."
        return {
            "name": "docker_daemon",
            "status": FAIL,
            "detail": add_docker_hint(detail, docker_host=docker_host),
        }
    if result.returncode != 0:
        detail = trim_output(result.stderr or result.stdout)
        return {
            "name": "docker_daemon",
            "status": FAIL,
            "detail": add_docker_hint(detail, docker_host=docker_host),
        }
    return {
        "name": "docker_daemon",
        "status": PASS,
        "detail": "docker ps completed successfully.",
    }


def ensure_docker_available(
    *,
    context: str,
    docker_executable: str = "docker",
    docker_host: str = "",
    timeout_seconds: int = 30,
) -> None:
    checks = check_docker_requirements(
        require_docker=True,
        docker_executable=docker_executable,
        docker_host=docker_host,
        timeout_seconds=timeout_seconds,
    )
    if any(check["status"] == FAIL for check in checks):
        raise RuntimeError(
            f"Docker is not available for {context}.\n"
            + format_docker_checks(checks)
        )


def format_docker_checks(checks: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"- [{check['status']}] {check['name']}: {check['detail']}"
        for check in checks
    )


def add_docker_hint(detail: str, *, docker_host: str = "") -> str:
    hints = docker_hints(detail, docker_host=docker_host)
    if not hints:
        return detail
    return detail.rstrip() + " " + " ".join(hints)


def docker_hints(detail: str, *, docker_host: str = "") -> list[str]:
    lowered = detail.lower()
    hints: list[str] = []
    if docker_host.startswith("unix://"):
        socket_path = Path(docker_host.removeprefix("unix://"))
        if not socket_path.exists():
            hints.append(f"Configured Docker socket does not exist: {socket_path}.")
        elif "permission denied" in lowered or "operation not permitted" in lowered:
            hints.append(
                f"Configured Docker socket exists but this process cannot connect to it: {socket_path}. "
                "Run from a WSL session allowed to access Docker Desktop, adjust Docker socket permissions/group "
                "outside this restricted process, or run the experiment in an environment with a local Docker daemon."
            )
    elif DOCKER_DESKTOP_WSL_SOCKET.exists():
        hints.append(
            "Docker Desktop WSL socket is visible; try "
            f"--docker-host unix://{DOCKER_DESKTOP_WSL_SOCKET} "
            "or set EDOS_DOCKER_HOST to that value."
        )
    if is_wsl():
        if (
            "wsl 2 distro" in lowered
            or "utilbindvsockanyport" in lowered
            or "cannot connect to the docker daemon" in lowered
            or "docker executable not found" in lowered
            or "permission denied" in lowered
            or "operation not permitted" in lowered
        ):
            hints.append(
                "This WSL session cannot reach Docker Desktop. Enable Docker Desktop "
                "Settings -> Resources -> WSL Integration for this distro, restart "
                "Docker Desktop, then run `wsl.exe --shutdown` and open WSL again; "
                "or install and start a Docker daemon inside WSL."
            )
    elif "cannot connect to the docker daemon" in lowered:
        hints.append("Start Docker daemon or Docker Desktop and retry.")
    return dedupe(hints)


def is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        version = Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False
    return "microsoft" in version or "wsl" in version


def dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def trim_output(value: str, limit: int = 500) -> str:
    compact = " ".join(value.strip().split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."
