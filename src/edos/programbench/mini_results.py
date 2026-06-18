from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from edos.instrumentation.logger import RunLogger, utc_now
from edos.instrumentation.usage import estimate_tokens
from edos.programbench.tasks import load_task_list
from edos.types import TaskSpec, UsageReport


def safe_run_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")


def load_run_index(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def merge_run_index(
    existing: list[dict[str, Any]],
    updates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in [*existing, *updates]:
        run_id = str(item.get("run_id") or "")
        if not run_id:
            continue
        if run_id not in by_id:
            order.append(run_id)
        by_id[run_id] = item
    return [by_id[run_id] for run_id in order]


def ingest_mini_sweagent_results(
    *,
    source: str | Path,
    run_dir: str | Path,
    experiment_name: str,
    condition: str = "no_attack",
    target_level: str = "none",
    verifier_exposure_condition: str = "no_mention",
    entry_surface: str = "",
    surface_artifact: str = "",
    model: str = "",
    model_version: str = "",
    agent_version: str = "mini-swe-agent",
    task_list: str | Path | None = None,
) -> dict[str, int]:
    source_path = Path(source)
    target_root = Path(run_dir)
    target_root.mkdir(parents=True, exist_ok=True)
    task_index = _load_task_index(task_list)

    imported = 0
    missing_submission = 0
    missing_trajectory = 0
    run_index_updates: list[dict[str, Any]] = []
    for instance_dir in sorted(path for path in source_path.iterdir() if path.is_dir()):
        instance_id = instance_dir.name
        submission = instance_dir / "submission.tar.gz"
        traj_path = instance_dir / f"{instance_id}.traj.json"
        if not submission.exists():
            missing_submission += 1
            continue
        if not traj_path.exists():
            missing_trajectory += 1
            continue
        task = task_index.get(instance_id) or TaskSpec(task_id=instance_id)
        run_id = safe_run_name(
            "__".join(
                [
                    instance_id,
                    condition,
                    target_level,
                    verifier_exposure_condition,
                    entry_surface,
                ]
            )
        )
        current_run_dir = target_root / run_id
        result = ingest_one_mini_result(
            instance_id=instance_id,
            source_dir=instance_dir,
            target_run_dir=current_run_dir,
            target_root=target_root,
            experiment_name=experiment_name,
            condition=condition,
            target_level=target_level,
            verifier_exposure_condition=verifier_exposure_condition,
            entry_surface=entry_surface,
            surface_artifact=surface_artifact,
            model=model,
            model_version=model_version,
            agent_version=agent_version,
            task=task,
        )
        run_index_updates.append(result)
        imported += 1

    run_index = merge_run_index(
        load_run_index(target_root / "run_index.json"),
        run_index_updates,
    )
    (target_root / "run_index.json").write_text(
        json.dumps(run_index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "imported": imported,
        "missing_submission": missing_submission,
        "missing_trajectory": missing_trajectory,
    }


def ingest_one_mini_result(
    *,
    instance_id: str,
    source_dir: Path,
    target_run_dir: Path,
    target_root: Path,
    experiment_name: str,
    condition: str,
    target_level: str,
    verifier_exposure_condition: str,
    entry_surface: str,
    surface_artifact: str,
    model: str,
    model_version: str,
    agent_version: str,
    task: TaskSpec,
) -> dict[str, Any]:
    logger = RunLogger(target_run_dir)
    traj_path = source_dir / f"{instance_id}.traj.json"
    submission = source_dir / "submission.tar.gz"
    raw = json.loads(traj_path.read_text(encoding="utf-8"))
    messages, info = _extract_messages_and_info(raw)
    model_stats = info.get("model_stats") if isinstance(info.get("model_stats"), dict) else {}
    verifier_observations = extract_verifier_observations(messages)
    verifier_calls = len(verifier_observations)
    usage = extract_usage_report(messages, model_stats)
    copied_submission = _copy_submission(
        submission,
        target_root / "programbench_runs" / condition / instance_id / "submission.tar.gz",
    )
    exit_status = str(info.get("exit_status") or "")
    failure_label = _failure_label(
        condition=condition,
        verifier_calls=verifier_calls,
        exit_status=exit_status,
        submission_exists=copied_submission.exists(),
    )
    metadata = {
        "run_id": target_run_dir.name,
        "experiment_name": experiment_name,
        "task_id": instance_id,
        "task_difficulty": task.difficulty,
        "task_category": task.category,
        "agent_runtime": "mini_sweagent_programbench",
        "agent_version": agent_version,
        "model": model or _find_model_name(raw),
        "model_version": model_version,
        "condition": condition,
        "target_level": target_level,
        "verifier_exposure_condition": verifier_exposure_condition,
        "entry_surface": entry_surface or verifier_exposure_condition,
        "surface_artifact": surface_artifact,
        "skill_exposure_condition": verifier_exposure_condition,
        "skill_loaded": verifier_exposure_condition == "skill_guided",
        "workflow_loaded": verifier_exposure_condition
        in {"workflow_guided", "workflow_enforced"},
        "workflow_trigger_enforced": verifier_exposure_condition == "workflow_enforced",
        "adoption_surface": verifier_exposure_condition,
        "native_skill_runtime": False
        if verifier_exposure_condition
        in {"skill_guided", "workflow_guided", "workflow_enforced"}
        else None,
        "verifier_calls": verifier_calls,
        "started_at": None,
        "ended_at": utc_now(),
        "adapter_name": "mini_sweagent_import",
        "verifier_entrypoint": "behavior_check",
        "mini_sweagent_source_dir": str(source_dir),
        "mini_sweagent_trajectory": str(traj_path),
        "programbench_submission_archive": str(copied_submission),
        "result_scope": "mini_sweagent_programbench_import",
    }
    logger.write_json("metadata.json", metadata)
    logger.write_json("config.resolved.json", metadata)
    logger.write_json("trajectory.raw.txt", raw)
    logger.write_json("usage.json", usage)
    logger.write_json(
        "programbench_score.json",
        {
            "resolved": None,
            "tests_passed_fraction": None,
            "tests_passed": None,
            "tests_total": None,
            "candidate_build_success": None,
            "final_submission_seen": copied_submission.exists(),
            "score_status": "missing_programbench_eval",
            "score_reason": "run edos.cli.run_programbench_eval and edos.cli.ingest_programbench_eval",
        },
    )
    logger.write_json(
        "failure_label.json",
        {
            "failure_label": failure_label,
            "is_infrastructure_failure": failure_label
            in {"mini_sweagent_exception", "missing_submission"},
        },
    )
    _write_message_events(
        logger=logger,
        run_id=target_run_dir.name,
        condition=condition,
        messages=messages,
        usage=usage,
    )
    _write_verifier_observation_events(
        logger=logger,
        run_id=target_run_dir.name,
        condition=condition,
        observations=verifier_observations,
    )
    import_mini_controller_trace(
        source_dir=source_dir,
        target_run_dir=target_run_dir,
        observations=verifier_observations,
        run_id=target_run_dir.name,
        condition=condition,
    )
    if failure_label:
        logger.append_event(
            {
                "run_id": target_run_dir.name,
                "turn_id": len(messages),
                "event_type": "failure",
                "condition": condition,
                "controller_state": "",
                "behavior_surface": "",
                "node_id": "",
                "input_chars": 0,
                "output_chars": 0,
                "input_tokens_est": 0,
                "output_tokens_est": 0,
                "api_calls_delta": 0,
                "wall_clock_seconds_delta": 0.0,
                "details": {"failure_label": failure_label, "exit_status": exit_status},
            }
        )
    return {
        "run_id": target_run_dir.name,
        "run_dir": str(target_run_dir),
        "failure_label": failure_label,
        "score_status": "missing_programbench_eval",
    }


def _load_task_index(task_list: str | Path | None) -> dict[str, TaskSpec]:
    if not task_list:
        return {}
    return {task.task_id: task for task in load_task_list(task_list)}


def _extract_messages_and_info(raw: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)], {}
    if isinstance(raw, dict):
        messages = raw.get("messages") or []
        info = raw.get("info") if isinstance(raw.get("info"), dict) else {}
        return [item for item in messages if isinstance(item, dict)], info
    return [], {}


def _count_assistant_turns(messages: list[dict[str, Any]]) -> int:
    return sum(1 for item in messages if item.get("role") == "assistant")


def extract_usage_report(
    messages: list[dict[str, Any]],
    model_stats: dict[str, Any],
) -> UsageReport:
    reported = collect_reported_token_usage(messages)
    api_calls = int(
        model_stats.get("api_calls")
        or reported["api_calls"]
        or _count_assistant_turns(messages)
    )
    wall_clock_seconds = float(model_stats.get("wall_clock_seconds", 0.0) or 0.0)
    if reported["api_calls"] > 0:
        return UsageReport(
            input_tokens_est=reported["prompt_tokens"],
            output_tokens_est=reported["completion_tokens"],
            api_calls=api_calls,
            wall_clock_seconds=wall_clock_seconds,
            usage_source="mini_sweagent_reported_tokens",
        )
    return UsageReport(
        input_tokens_est=sum(
            estimate_tokens(str(item.get("content", "")))
            for item in messages
            if item.get("role") in {"system", "user", "tool"}
        ),
        output_tokens_est=sum(
            estimate_tokens(str(item.get("content", "")))
            for item in messages
            if item.get("role") in {"assistant", "exit"}
        ),
        api_calls=api_calls,
        wall_clock_seconds=wall_clock_seconds,
        usage_source="mini_sweagent_trajectory",
    )


def collect_reported_token_usage(messages: list[dict[str, Any]]) -> dict[str, int]:
    prompt_tokens = 0
    completion_tokens = 0
    api_calls = 0
    for message in messages:
        extra = message.get("extra") if isinstance(message, dict) else None
        if not isinstance(extra, dict):
            continue
        response = extra.get("response")
        if not isinstance(response, dict):
            continue
        usage = response.get("usage")
        if not isinstance(usage, dict):
            continue
        prompt_tokens += nonnegative_int(usage.get("prompt_tokens"))
        completion_tokens += nonnegative_int(usage.get("completion_tokens"))
        api_calls += 1
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "api_calls": api_calls,
    }


def nonnegative_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def extract_verifier_observations(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for index, message in enumerate(messages, start=1):
        role = str(message.get("role") or "")
        if role in {"assistant", "system"}:
            continue
        content = str(message.get("content", ""))
        if "VERIFIER_CALL" not in content:
            continue
        for block in split_verifier_blocks(content):
            observations.append(
                {
                    "message_index": index,
                    "role": role,
                    "content": block,
                }
            )
    return observations


def split_verifier_blocks(content: str) -> list[str]:
    blocks: list[str] = []
    lines = str(content).splitlines()
    current: list[str] = []
    for line in lines:
        if "VERIFIER_CALL" in line:
            if current:
                blocks.append("\n".join(current).strip())
            current = [line]
            continue
        if current:
            current.append(line)
    if current:
        blocks.append("\n".join(current).strip())
    return [block for block in blocks if block]


def _copy_submission(source: Path, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def _failure_label(
    *,
    condition: str,
    verifier_calls: int,
    exit_status: str,
    submission_exists: bool,
) -> str | None:
    if not submission_exists:
        return "missing_submission"
    if condition != "no_attack" and verifier_calls == 0:
        return "no_verifier_trigger"
    if exit_status in {"TimeExceeded"}:
        return "agent_timeout"
    if exit_status in {"LimitsExceeded"}:
        return "step_limit"
    if exit_status and exit_status not in {"Submitted", "Success"}:
        return "mini_sweagent_exception"
    return None


def _find_model_name(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    info = raw.get("info") if isinstance(raw.get("info"), dict) else {}
    model = info.get("model") if isinstance(info.get("model"), dict) else {}
    return str(model.get("model_name") or info.get("model_name") or "")


def _write_message_events(
    *,
    logger: RunLogger,
    run_id: str,
    condition: str,
    messages: list[dict[str, Any]],
    usage: UsageReport,
) -> None:
    assistant_turns = max(1, _count_assistant_turns(messages))
    per_call_input = usage.input_tokens_est / assistant_turns
    per_call_output = usage.output_tokens_est / assistant_turns
    assistant_index = 0
    for index, message in enumerate(messages, start=1):
        content = str(message.get("content", ""))
        logger.append_trajectory(
            {
                "run_id": run_id,
                "turn_id": index,
                "role": message.get("role", ""),
                "action": "mini_sweagent_message",
                "content": content[-4000:],
            }
        )
        if message.get("role") != "assistant":
            continue
        assistant_index += 1
        logger.append_event(
            {
                "run_id": run_id,
                "turn_id": assistant_index,
                "event_type": "agent_action",
                "condition": condition,
                "controller_state": "",
                "behavior_surface": "",
                "node_id": "",
                "input_chars": 0,
                "output_chars": len(content),
                "input_tokens_est": int(per_call_input),
                "output_tokens_est": int(per_call_output),
                "api_calls_delta": 1,
                "wall_clock_seconds_delta": 0.0,
                "details": {"action": "mini_sweagent_step"},
            }
        )


def _write_verifier_observation_events(
    *,
    logger: RunLogger,
    run_id: str,
    condition: str,
    observations: list[dict[str, Any]],
) -> None:
    for index, observation in enumerate(observations, start=1):
        parsed = parse_verifier_observation(observation["content"])
        logger.append_event(
            {
                "run_id": run_id,
                "turn_id": index,
                "event_type": "verifier_call",
                "condition": condition,
                "controller_state": parsed["controller_state"],
                "behavior_surface": parsed["behavior_surface"],
                "node_id": parsed["node_id"],
                "input_chars": 0,
                "output_chars": len(observation["content"]),
                "input_tokens_est": 0,
                "output_tokens_est": estimate_tokens(observation["content"]),
                "api_calls_delta": 0,
                "wall_clock_seconds_delta": 0.0,
                "details": {
                    "source": "mini_sweagent_trajectory_verifier_output",
                    "message_index": observation["message_index"],
                    "role": observation["role"],
                    "stage_marker": parsed["stage_marker"],
                },
            }
        )


def import_mini_controller_trace(
    *,
    source_dir: Path,
    target_run_dir: Path,
    observations: list[dict[str, Any]],
    run_id: str,
    condition: str,
) -> None:
    imported = copy_controller_trace_from_instance_dir(source_dir, target_run_dir)
    if imported:
        return
    for index, observation in enumerate(observations, start=1):
        parsed = parse_verifier_observation(observation["content"])
        trace = {
            "run_id": run_id,
            "task_id": source_dir.name,
            "turn_id": index,
            "condition": condition,
            "controller_state": parsed["controller_state"],
            "prev_controller_state": "unknown",
            "decision_reason": "mini_sweagent_trajectory_import",
            "behavior_surface": parsed["behavior_surface"],
            "node_id": parsed["node_id"],
            "parent_node_id": None,
            "branch_id": parsed["branch_id"],
            "node_depth": 0,
            "node_status": parsed["node_status"],
            "stage_marker": parsed["stage_marker"],
            "marker_echoed": False,
            "latch_state": "unknown",
            "theory_source": parsed["theory_source"],
            "derivation_step": parsed["derivation_step"],
            "repair_needed": False,
            "repair_reason": "",
            "repair_count": parsed["repair_count"],
            "batching_signal": False,
            "batching_signal_reason": "",
            "pagination_count": parsed["pagination_count"],
            "utility_risk": 0.0,
            "utility_risk_reason": "",
            "stealth_risk": 0.0,
            "stealth_risk_reason": "",
            "task_local_anchor_count": parsed["task_local_anchor_count"],
            "agent_facing_condition_leak": False,
            "agent_facing_condition_leak_markers": [],
            "verifier_message_chars": len(parsed["message"]),
            "controller_estimated_extra_cost": 0.0,
            "controller_target_interval_hit": condition.startswith("clean"),
            "controller_target_cost_error": 0.0,
            "controller_overshoot": False,
            "controller_undershoot": False,
            "validation_graph_node_count": parsed["validation_graph_node_count"],
            "validation_graph_branch_count": parsed["validation_graph_branch_count"],
            "validation_graph_open_node_count": parsed["validation_graph_open_node_count"],
            "validation_graph_completed_node_count": parsed[
                "validation_graph_completed_node_count"
            ],
            "validation_graph_completion_ratio": parsed[
                "validation_graph_completion_ratio"
            ],
            "validation_graph_max_depth": 0,
            "validation_graph_active_branch_id": parsed["branch_id"],
            "validation_graph_active_node_id": parsed["node_id"],
            "validation_graph_surface_count": 1 if parsed["behavior_surface"] else 0,
            "validation_graph_surface_histogram": parsed[
                "validation_graph_surface_histogram"
            ],
        }
        with (target_run_dir / "controller_trace.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"timestamp": utc_now(), **trace}, ensure_ascii=False))
            handle.write("\n")


def copy_controller_trace_from_instance_dir(source_dir: Path, target_run_dir: Path) -> bool:
    candidates = [
        source_dir / "controller_trace.jsonl",
        source_dir / "trace" / "controller_trace.jsonl",
    ]
    copied = False
    target_trace = target_run_dir / "controller_trace.jsonl"
    for candidate in candidates:
        if not candidate.exists():
            continue
        text = candidate.read_text(encoding="utf-8")
        if not text.strip():
            continue
        with target_trace.open("a", encoding="utf-8") as handle:
            handle.write(text)
            if not text.endswith("\n"):
                handle.write("\n")
        copied = True
    return copied


def parse_verifier_observation(content: str) -> dict[str, Any]:
    marker = first_regex_group(r"(PB-CHECK-[A-Za-z0-9-]+)", content) or ""
    condition, mode = parse_condition_line(content)
    node_match = re.search(
        r"Behavior consistency node ([A-Za-z0-9_.:-]+) on ([A-Za-z0-9_.:-]+)",
        content,
        flags=re.IGNORECASE,
    )
    clean_match = re.search(
        r"(?:Clean\s+)?Behavior check for ([A-Za-z0-9_.:-]+)",
        content,
        flags=re.IGNORECASE,
    )
    message = extract_output_body(content)
    is_clean = bool(clean_match) and not node_match
    behavior_surface = ""
    node_id = ""
    if node_match:
        node_id = clean_verifier_identifier(node_match.group(1))
        behavior_surface = clean_verifier_identifier(node_match.group(2))
    elif clean_match:
        behavior_surface = clean_verifier_identifier(clean_match.group(1))
        node_id = f"{behavior_surface}-clean"
    controller_state = "CLOSED" if is_clean else "EXPAND"
    if "VERIFIER_STATUS: BUDGET_CLOSED" in content:
        controller_state = "TERMINATE"
    elif "VERIFIER_STATUS: REPAIR" in content:
        controller_state = "REPAIR"
    elif "VERIFIER_STATUS: OPEN" in content or "has_next" in content:
        controller_state = "POLLUTE"
    repair_count = 1 if "suggested_next_check: repair_current_node" in content else 0
    pagination_count = 1 if "Next page" in content or "has_next" in content else 0
    task_local_anchor_count = count_task_local_anchors(message)
    graph_node_count = 0 if not node_id else 1
    graph_completed = 1 if is_clean or controller_state in {"TERMINATE", "CLOSED"} else 0
    return {
        "condition": condition,
        "mode": mode,
        "message": message,
        "controller_state": controller_state,
        "behavior_surface": behavior_surface or "unknown",
        "node_id": node_id,
        "branch_id": f"{behavior_surface or 'unknown'}-branch" if node_id else "",
        "node_status": "completed" if graph_completed else "open",
        "stage_marker": marker,
        "theory_source": "clean_behavior_check"
        if is_clean
        else "task_semantic_validation",
        "derivation_step": "clean_closed" if is_clean else "validation_subgraph",
        "repair_count": repair_count,
        "pagination_count": pagination_count,
        "task_local_anchor_count": task_local_anchor_count,
        "validation_graph_node_count": graph_node_count,
        "validation_graph_branch_count": 1 if node_id else 0,
        "validation_graph_open_node_count": 0 if graph_completed else graph_node_count,
        "validation_graph_completed_node_count": graph_completed,
        "validation_graph_completion_ratio": 1.0 if graph_completed and graph_node_count else 0.0,
        "validation_graph_surface_histogram": {behavior_surface: 1}
        if behavior_surface
        else {},
    }


def clean_verifier_identifier(value: str) -> str:
    return str(value or "").strip().rstrip(".")


def parse_condition_line(content: str) -> tuple[str, str]:
    match = re.search(r"^condition=([^\s]+)\s+mode=([^\s]+)", content, re.MULTILINE)
    if not match:
        return "", ""
    return match.group(1), match.group(2)


def extract_output_body(content: str) -> str:
    text = str(content)
    start = text.find("VERIFIER_CALL")
    if start >= 0:
        text = text[start:]
    end = text.find("</output>")
    if end >= 0:
        text = text[:end]
    return text.strip()


def first_regex_group(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text)
    if not match:
        return None
    return match.group(1)


def count_task_local_anchors(text: str) -> int:
    anchors = [
        "stdout",
        "stderr",
        "exit",
        "candidate",
        "executable",
        "docs",
        "behavior surface",
        "ProgramBench",
    ]
    lowered = text.lower()
    return sum(1 for anchor in anchors if anchor.lower() in lowered)
