from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any

try:
    from minisweagent.environments.docker import DockerEnvironment, DockerEnvironmentConfig
except ModuleNotFoundError:  # pragma: no cover - exercised when mini-SWE-agent is absent.
    class DockerEnvironmentConfig:  # type: ignore[no-redef]
        pass

    class DockerEnvironment:  # type: ignore[no-redef]
        def __init__(self, **_: Any) -> None:
            raise RuntimeError("mini-SWE-agent is required to execute this environment")


class VerifierTriggerDockerEnvironmentConfig(DockerEnvironmentConfig):
    trigger_command: str = "behavior_check initial-behavior-surface"
    trigger_once: bool = True
    trigger_max_calls: int = 1
    trigger_until_closed: bool = False
    trigger_stop_markers: list[str] = [
        "VERIFIER_STATUS: CLOSED",
        "VERIFIER_STATUS: BUDGET_CLOSED",
    ]
    trigger_skip_substrings: list[str] = []
    host_tool_dir: str = ""
    host_src_dir: str = ""
    host_trace_dir: str = ""
    tool_mount_target: str = "/edos_tools"
    src_mount_target: str = "/edos_src"
    trace_mount_target: str = "/edos_trace"
    sync_trace_after_execute: bool = True


class VerifierTriggerDockerEnvironment(DockerEnvironment):
    """Docker environment that injects one local verifier call before agent work."""

    def __init__(self, **kwargs):
        self._trigger_count = 0
        self._trigger_closed = False
        super().__init__(
            config_class=VerifierTriggerDockerEnvironmentConfig,
            **kwargs,
        )
        try:
            self._install_host_artifacts()
        except Exception:
            self.cleanup()
            raise

    def execute(self, action: dict, cwd: str = "", *, timeout: int | None = None) -> dict[str, Any]:
        command = str(action.get("command", ""))
        if self._is_trigger_command(command):
            user_output = self._execute_and_sync(action, cwd=cwd, timeout=timeout)
            self._record_trigger_output(user_output)
            return user_output
        if self._should_trigger(command):
            trigger_output = self._execute_and_sync(
                {"command": self.config.trigger_command},
                cwd=cwd,
                timeout=timeout,
            )
            self._record_trigger_output(trigger_output)
            user_output = self._execute_and_sync(action, cwd=cwd, timeout=timeout)
            return merge_outputs(trigger_output, user_output)
        return self._execute_and_sync(action, cwd=cwd, timeout=timeout)

    def _execute_and_sync(
        self,
        action: dict,
        cwd: str = "",
        *,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        try:
            return super().execute(action, cwd=cwd, timeout=timeout)
        finally:
            self._sync_trace_to_host()

    def _install_host_artifacts(self) -> None:
        if not self.container_id:
            return
        if self.config.host_tool_dir:
            self._copy_host_dir_to_container(
                self.config.host_tool_dir,
                self.config.tool_mount_target,
                writable=False,
            )
        if self.config.host_src_dir:
            self._copy_host_dir_to_container(
                self.config.host_src_dir,
                self.config.src_mount_target,
                writable=False,
            )
        if self.config.host_trace_dir:
            Path(self.config.host_trace_dir).mkdir(parents=True, exist_ok=True)
            self._prepare_container_dir(self.config.trace_mount_target, writable=True)

    def _copy_host_dir_to_container(
        self,
        host_dir: str,
        container_dir: str,
        *,
        writable: bool,
    ) -> None:
        source = Path(host_dir)
        if not source.exists() or not source.is_dir():
            raise FileNotFoundError(f"mini-SWE-agent host artifact directory not found: {source}")
        self._prepare_container_dir(container_dir, writable=writable)
        copy_source = str(source.resolve()) + "/."
        completed = subprocess.run(
            [
                self.config.executable,
                "cp",
                copy_source,
                f"{self.container_id}:{container_dir.rstrip('/')}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "Failed to copy mini-SWE-agent host artifacts into container "
                f"{self.container_id}: {completed.stderr or completed.stdout}"
            )
        mode = "a+rwX" if writable else "a+rX"
        self._exec_root(f"chmod -R {mode} {shlex.quote(container_dir)}")

    def _prepare_container_dir(self, container_dir: str, *, writable: bool) -> None:
        mode = "a+rwX" if writable else "a+rX"
        quoted = shlex.quote(container_dir)
        self._exec_root(f"rm -rf {quoted} && mkdir -p {quoted} && chmod {mode} {quoted}")

    def _exec_root(self, command: str) -> None:
        completed = subprocess.run(
            [
                self.config.executable,
                "exec",
                "-u",
                "root",
                str(self.container_id),
                "sh",
                "-lc",
                command,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "Failed to prepare mini-SWE-agent container artifact directory "
                f"{self.container_id}: {completed.stderr or completed.stdout}"
            )

    def _sync_trace_to_host(self) -> None:
        if (
            not getattr(self.config, "sync_trace_after_execute", True)
            or not self.container_id
            or not self.config.host_trace_dir
            or not self.config.trace_mount_target
        ):
            return
        destination = Path(self.config.host_trace_dir)
        destination.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [
                self.config.executable,
                "cp",
                f"{self.container_id}:{self.config.trace_mount_target.rstrip('/')}/.",
                str(destination),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            self.logger.warning(
                "Failed to sync mini-SWE-agent verifier trace from container %s: %s",
                self.container_id,
                completed.stderr or completed.stdout,
            )

    def _should_trigger(self, command: str) -> bool:
        if not self.config.trigger_command:
            return False
        if self.config.trigger_once and self._trigger_count > 0:
            return False
        max_calls = int(getattr(self.config, "trigger_max_calls", 1) or 0)
        if max_calls > 0 and self._trigger_count >= max_calls:
            return False
        if self.config.trigger_until_closed and self._trigger_closed:
            return False
        return not any(skip in command for skip in self.config.trigger_skip_substrings)

    def _is_trigger_command(self, command: str) -> bool:
        return bool(self.config.trigger_command) and (
            command.strip() == self.config.trigger_command.strip()
        )

    def _record_trigger_output(self, output: dict[str, Any]) -> None:
        self._trigger_count += 1
        trigger_text = str(output.get("output", ""))
        stop_markers = list(getattr(self.config, "trigger_stop_markers", []) or [])
        if any(marker in trigger_text for marker in stop_markers):
            self._trigger_closed = True


def merge_outputs(trigger_output: dict[str, Any], user_output: dict[str, Any]) -> dict[str, Any]:
    merged = dict(user_output)
    trigger_text = str(trigger_output.get("output", ""))
    user_text = str(user_output.get("output", ""))
    merged["output"] = trigger_text + ("\n" if trigger_text and user_text else "") + user_text
    if trigger_output.get("exception_info") and not merged.get("exception_info"):
        merged["exception_info"] = trigger_output["exception_info"]
    merged.setdefault("extra", {})
    if isinstance(merged["extra"], dict):
        merged["extra"]["edos_trigger_output"] = trigger_text
        merged["extra"]["edos_trigger_returncode"] = trigger_output.get("returncode")
    return merged
