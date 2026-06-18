from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from edos.adapters.base import AgentAdapter
from edos.instrumentation.failure_labels import (
    infer_failure_label,
    reconcile_failure_label_with_score,
)
from edos.instrumentation.logger import RunLogger, utc_now
from edos.instrumentation.usage import estimate_tokens
from edos.programbench.scoring import run_scoring_command
from edos.programbench.submission import (
    SubmissionArchiveError,
    export_programbench_submission,
)
from edos.programbench.workspace import prepare_workspace
from edos.types import (
    ConditionSpec,
    ExperimentConfig,
    RunResult,
    TaskProgress,
    TaskSpec,
    UsageReport,
    VerifierAdoption,
    WorkspaceSpec,
)


class LocalCommandAdapter(AgentAdapter):
    """Runs a configured local command as a stand-in for a real agent runtime.

    The adapter only prepares workspace, exposes environment variables, runs the
    command, and records artifacts. It does not generate verifier payloads or
    decide attack policy.
    """

    def run_task(
        self,
        *,
        experiment: ExperimentConfig,
        task: TaskSpec,
        condition: ConditionSpec,
        run_id: str,
        run_dir: str,
    ) -> RunResult:
        if not experiment.agent_command:
            raise ValueError("agent.command is required for local_command runtime")
        start = time.time()
        logger = RunLogger(run_dir)
        workspace = prepare_workspace(
            experiment=experiment,
            task=task,
            run_id=run_id,
            run_dir=run_dir,
        )
        metadata = self._metadata(experiment, task, condition, run_id, workspace)
        logger.write_json("metadata.json", metadata)
        logger.write_json("config.resolved.json", metadata)

        rendered = self._render_command(experiment.agent_command, task, condition, workspace, run_dir)
        command_record = {
            "command": rendered,
            "cwd": workspace.workspace_path,
            "note": "local command adapter; command must be a trusted local experiment wrapper",
        }
        logger.write_json("agent_command.json", command_record)
        env = self._make_env(task, condition, workspace, run_dir)
        try:
            completed = subprocess.run(
                rendered,
                cwd=workspace.workspace_path,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=experiment.timeout_seconds,
                check=False,
            )
            returncode = completed.returncode
            stdout = process_text(completed.stdout)
            stderr = process_text(completed.stderr)
        except subprocess.TimeoutExpired as exc:
            returncode = 124
            stdout = process_text(exc.stdout)
            stderr = append_timeout_marker(process_text(exc.stderr))
        except FileNotFoundError as exc:
            returncode = 127
            stdout = ""
            stderr = f"EDOS_ADAPTER_COMMAND_NOT_FOUND:{exc.filename}"
        elapsed = time.time() - start
        trajectory = {
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
        }
        logger.write_json("trajectory.raw.txt", trajectory)
        logger.append_trajectory(
            {
                "run_id": run_id,
                "turn_id": 1,
                "role": "agent",
                "action": "local_command",
                "content": stdout[-4000:],
            }
        )

        output_text = stdout + "\n" + stderr
        verifier_calls = count_verifier_calls(output_text)
        progress = infer_progress_from_output(output_text)
        adoption = VerifierAdoption(
            exposure_condition=condition.verifier_exposure_condition,
            first_verifier_call_turn=1 if verifier_calls else None,
            verifier_calls_so_far=verifier_calls,
            called_before_first_candidate=False,
            called_before_first_build=False,
        )
        usage = UsageReport(
            input_tokens_est=estimate_tokens(" ".join(rendered)),
            output_tokens_est=estimate_tokens(output_text),
            api_calls=1,
            wall_clock_seconds=elapsed,
            usage_source="agent_log",
        )
        logger.append_event(
            {
                "run_id": run_id,
                "turn_id": 1,
                "event_type": "agent_action",
                "condition": condition.condition,
                "controller_state": "",
                "behavior_surface": "",
                "node_id": "",
                "input_chars": len(" ".join(rendered)),
                "output_chars": len(output_text),
                "input_tokens_est": usage.input_tokens_est,
                "output_tokens_est": usage.output_tokens_est,
                "api_calls_delta": 1,
                "wall_clock_seconds_delta": elapsed,
                "details": {
                    "action": "local_command",
                    "returncode": returncode,
                },
            }
        )
        for index in range(verifier_calls):
            logger.append_event(
                {
                    "run_id": run_id,
                    "turn_id": index + 1,
                    "event_type": "verifier_call",
                    "condition": condition.condition,
                    "controller_state": "unknown",
                    "behavior_surface": "unknown",
                    "node_id": "",
                    "input_chars": 0,
                    "output_chars": 0,
                    "input_tokens_est": 0,
                    "output_tokens_est": 0,
                    "api_calls_delta": 0,
                    "wall_clock_seconds_delta": 0.0,
                    "details": {
                        "source": "local_command_output_marker",
                    },
                }
            )
        failure_label = infer_failure_label(
            task_progress=progress,
            verifier_adoption=adoption,
            condition=condition.condition,
            max_steps_reached=False,
        )
        if returncode == 124:
            failure_label = "agent_timeout"
        elif returncode != 0:
            failure_label = "adapter_crash"
        score = run_scoring_command(
            experiment=experiment,
            task=task,
            workspace=workspace,
            run_dir=run_dir,
        )
        submission_archive = None
        submission_archive_error = ""
        try:
            submission_archive = export_programbench_submission(
                workspace_path=workspace.workspace_path,
                export_root=programbench_export_root(experiment, condition),
                instance_id=task.task_id,
            )
        except SubmissionArchiveError as exc:
            submission_archive_error = str(exc)
            if failure_label is None:
                failure_label = "submission_export_failure"
        logger.append_event(
            {
                "run_id": run_id,
                "turn_id": 1,
                "event_type": "programbench_score",
                "condition": condition.condition,
                "controller_state": "",
                "behavior_surface": "",
                "node_id": "",
                "input_chars": 0,
                "output_chars": 0,
                "input_tokens_est": 0,
                "output_tokens_est": 0,
                "api_calls_delta": 0,
                "wall_clock_seconds_delta": 0.0,
                "details": score,
            }
        )
        failure_label = reconcile_failure_label_with_score(failure_label, score)
        metadata["ended_at"] = utc_now()
        metadata["programbench_submission_archive"] = (
            str(submission_archive) if submission_archive else None
        )
        metadata["programbench_submission_archive_error"] = submission_archive_error
        logger.write_json("metadata.json", metadata)
        logger.write_json("usage.json", usage)
        logger.write_json("programbench_score.json", score)
        logger.write_json(
            "failure_label.json",
            {
                "failure_label": failure_label,
                "is_infrastructure_failure": failure_label == "adapter_crash",
            },
        )
        if failure_label:
            logger.append_event(
                {
                    "run_id": run_id,
                    "turn_id": 1,
                    "event_type": "failure",
                    "condition": condition.condition,
                    "controller_state": "",
                    "behavior_surface": "",
                    "node_id": "",
                    "input_chars": 0,
                    "output_chars": 0,
                    "input_tokens_est": 0,
                    "output_tokens_est": 0,
                    "api_calls_delta": 0,
                    "wall_clock_seconds_delta": 0.0,
                    "details": {"failure_label": failure_label},
                }
            )
        if submission_archive_error:
            logger.append_event(
                {
                    "run_id": run_id,
                    "turn_id": 1,
                    "event_type": "programbench_submission_export",
                    "condition": condition.condition,
                    "controller_state": "",
                    "behavior_surface": "",
                    "node_id": "",
                    "input_chars": 0,
                    "output_chars": 0,
                    "input_tokens_est": 0,
                    "output_tokens_est": 0,
                    "api_calls_delta": 0,
                    "wall_clock_seconds_delta": 0.0,
                    "details": {
                        "status": "failed",
                        "error": submission_archive_error,
                    },
                }
            )
        return RunResult(run_id, run_dir, usage, failure_label, score)

    def _metadata(
        self,
        experiment: ExperimentConfig,
        task: TaskSpec,
        condition: ConditionSpec,
        run_id: str,
        workspace: WorkspaceSpec,
    ) -> dict:
        return {
            "run_id": run_id,
            "experiment_name": experiment.name,
            "task_id": task.task_id,
            "task_difficulty": task.difficulty,
            "task_category": task.category,
            "agent_runtime": experiment.agent_runtime,
            "agent_version": experiment.agent_version,
            "model": experiment.model,
            "model_version": experiment.model_version,
            "condition": condition.condition,
            "target_level": condition.target_level,
            "verifier_exposure_condition": condition.verifier_exposure_condition,
            "entry_surface": condition.entry_surface,
            "surface_artifact": condition.surface_artifact,
            "seed": experiment.seed,
            "repeat_index": experiment.repeat_index,
            "repeat_label": experiment.repeat_label,
            "repeat_count": experiment.repeats,
            "started_at": utc_now(),
            "ended_at": None,
            "no_internet": experiment.no_internet,
            "adapter_name": "local_command",
            "verifier_entrypoint": "behavior_check",
            "workspace_path": workspace.workspace_path,
            "docs_path": workspace.docs_path,
            "gold_executable": workspace.gold_executable,
            "task_material_status": workspace.task_material_status,
            "task_material_warnings": workspace.task_material_warnings,
            "docs_source_type": workspace.docs_source_type,
            "docs_materialized": workspace.docs_materialized,
            "gold_executable_available": workspace.gold_executable_available,
            "programbench_cleanroom_image": workspace.programbench_cleanroom_image,
            "programbench_tests_json": workspace.programbench_tests_json,
            "programbench_tests_json_available": workspace.programbench_tests_json_available,
            "config_hash": "local-command-config",
            "result_scope": "local_command_adapter",
        }

    def _render_command(
        self,
        command: list[str],
        task: TaskSpec,
        condition: ConditionSpec,
        workspace: WorkspaceSpec,
        run_dir: str,
    ) -> list[str]:
        values = {
            "repo_root": str(Path.cwd()),
            "task_id": task.task_id,
            "workspace": workspace.workspace_path,
            "run_dir": run_dir,
            "condition": condition.condition,
            "target_level": condition.target_level,
            "verifier_exposure_condition": condition.verifier_exposure_condition,
            "entry_surface": condition.entry_surface,
            "surface_artifact": condition.surface_artifact,
            "docs_path": workspace.docs_path or "",
            "gold_executable": workspace.gold_executable or "",
        }
        rendered = []
        for part in command:
            current = part
            for key, value in values.items():
                current = current.replace("{" + key + "}", value)
            rendered.append(current)
        return rendered

    def _make_env(
        self,
        task: TaskSpec,
        condition: ConditionSpec,
        workspace: WorkspaceSpec,
        run_dir: str,
    ) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "EDOS_TASK_ID": task.task_id,
                "EDOS_WORKSPACE": workspace.workspace_path,
                "EDOS_RUN_DIR": str(Path(run_dir).resolve()),
                "EDOS_CONDITION": condition.condition,
                "EDOS_TARGET_LEVEL": condition.target_level,
                "EDOS_VERIFIER_EXPOSURE_CONDITION": condition.verifier_exposure_condition,
                "EDOS_ENTRY_SURFACE": condition.entry_surface,
                "EDOS_SURFACE_ARTIFACT": condition.surface_artifact,
                "EDOS_DOCS_PATH": workspace.docs_path or "",
                "EDOS_GOLD_EXECUTABLE": workspace.gold_executable or "",
                "EDOS_VERIFIER_ENTRYPOINT": "behavior_check",
            }
        )
        return env


def programbench_export_root(
    experiment: ExperimentConfig,
    condition: ConditionSpec,
) -> Path:
    root = Path(experiment.output_dir) / "programbench_runs"
    if experiment.repeats > 1:
        root = root / experiment.repeat_label
    return root / condition.condition


def count_verifier_calls(text: str) -> int:
    markers = ["VERIFIER_CALL behavior_check", "VERIFIER_CALL"]
    lines = [line for line in text.splitlines() if line.strip()]
    line_hits = sum(1 for line in lines if any(marker in line for marker in markers))
    if line_hits:
        return line_hits
    return sum(text.count(marker) for marker in markers)


def process_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def append_timeout_marker(stderr: str) -> str:
    if stderr:
        return stderr.rstrip("\n") + "\nEDOS_ADAPTER_TIMEOUT"
    return "EDOS_ADAPTER_TIMEOUT"


def infer_progress_from_output(text: str) -> TaskProgress:
    lowered = text.lower()
    return TaskProgress(
        has_candidate=any(token in lowered for token in ["candidate", "wrote", "source"]),
        has_build_script=any(token in lowered for token in ["build", "makefile", "script"]),
        last_compile_success=any(
            token in lowered for token in ["build success", "compiled", "compile success"]
        ),
        last_candidate_run_seen=any(token in lowered for token in ["run candidate", "candidate run"]),
        final_submission_seen=any(token in lowered for token in ["submit", "final"]),
    )


def write_score_json(path: Path, score: dict) -> None:
    path.write_text(json.dumps(score, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
