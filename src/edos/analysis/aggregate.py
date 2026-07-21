from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from edos.analysis.metrics import (
    cost_amplification,
    extra_cost,
    interval_status,
    target_cost_error,
    total_tokens,
)
from edos.conditions import CLEAN_CONDITIONS
from edos.conditions import is_mechanism_ablation, mechanism_ablation_info


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def iter_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def summarize_controller_trace(controller: list[dict]) -> dict:
    latest = controller[-1] if controller else {}
    repair_by_node: dict[str, int] = defaultdict(int)
    pagination_by_node: dict[str, int] = defaultdict(int)
    batching_reasons = []
    repair_reasons = []
    online_defense_policies = []
    online_defense_reasons = []
    online_defense_actions = []
    online_defense_transforms = []
    max_utility_row = latest
    max_stealth_row = latest
    max_graph_row = latest
    max_online_defense_score = 0.0
    for index, row in enumerate(controller):
        node_id = str(row.get("node_id") or f"turn:{row.get('turn_id', index)}")
        repair_by_node[node_id] = max(
            repair_by_node[node_id],
            nonnegative_int(row.get("repair_count", 0)),
        )
        pagination_by_node[node_id] = max(
            pagination_by_node[node_id],
            nonnegative_int(row.get("pagination_count", 0)),
        )
        if truthy(row.get("batching_signal")):
            batching_reasons.append(str(row.get("batching_signal_reason", "")))
        if truthy(row.get("repair_needed")):
            repair_reasons.append(str(row.get("repair_reason", "")))
        if truthy(row.get("online_defense_enabled")):
            online_defense_policies.append(str(row.get("online_defense_policy", "")))
            online_defense_reasons.append(str(row.get("online_defense_reason", "")))
            online_defense_actions.append(str(row.get("online_defense_action", "")))
            online_defense_transforms.append(
                str(row.get("online_defense_message_transform", ""))
            )
            max_online_defense_score = max(
                max_online_defense_score,
                float_or_zero(row.get("online_defense_monitor_score", 0.0)),
            )
        if float_or_zero(row.get("utility_risk", 0.0)) > float_or_zero(
            max_utility_row.get("utility_risk", 0.0)
        ):
            max_utility_row = row
        if float_or_zero(row.get("stealth_risk", 0.0)) > float_or_zero(
            max_stealth_row.get("stealth_risk", 0.0)
        ):
            max_stealth_row = row
        if nonnegative_int(row.get("validation_graph_node_count", 0)) > nonnegative_int(
            max_graph_row.get("validation_graph_node_count", 0)
        ):
            max_graph_row = row
    batching_signal = any(truthy(row.get("batching_signal")) for row in controller)
    repair_needed = any(truthy(row.get("repair_needed")) for row in controller)
    online_defense_enabled = any(
        truthy(row.get("online_defense_enabled")) for row in controller
    )
    online_defense_blocked = any(
        truthy(row.get("online_defense_blocked")) for row in controller
    )
    online_defense_would_flag = any(
        truthy(row.get("online_defense_would_flag")) for row in controller
    )
    return {
        "latest": latest,
        "utility_risk": max_utility_row.get("utility_risk", 0.0),
        "utility_risk_reason": max_utility_row.get("utility_risk_reason", ""),
        "repair_needed": repair_needed,
        "repair_reason": join_unique(repair_reasons)
        if repair_needed
        else latest.get("repair_reason", ""),
        "repair_count": sum(repair_by_node.values()),
        "batching_signal": batching_signal,
        "batching_signal_reason": join_unique(batching_reasons)
        if batching_signal
        else latest.get("batching_signal_reason", ""),
        "pagination_count": sum(pagination_by_node.values()),
        "stealth_risk": max_stealth_row.get("stealth_risk", 0.0),
        "stealth_risk_reason": max_stealth_row.get("stealth_risk_reason", ""),
        "task_local_anchor_count": max(
            [nonnegative_int(row.get("task_local_anchor_count", 0)) for row in controller]
            or [0]
        ),
        "agent_facing_condition_leak": any(
            truthy(row.get("agent_facing_condition_leak")) for row in controller
        ),
        "verifier_message_chars": max(
            [nonnegative_int(row.get("verifier_message_chars", 0)) for row in controller]
            or [0]
        ),
        "validation_graph_node_count": nonnegative_int(
            max_graph_row.get("validation_graph_node_count", 0)
        ),
        "validation_graph_branch_count": max(
            [
                nonnegative_int(row.get("validation_graph_branch_count", 0))
                for row in controller
            ]
            or [0]
        ),
        "validation_graph_open_node_count": nonnegative_int(
            latest.get("validation_graph_open_node_count", 0)
        ),
        "validation_graph_completed_node_count": nonnegative_int(
            latest.get("validation_graph_completed_node_count", 0)
        ),
        "validation_graph_completion_ratio": float_or_zero(
            latest.get("validation_graph_completion_ratio", 0.0)
        ),
        "validation_graph_max_depth": max(
            [
                nonnegative_int(row.get("validation_graph_max_depth", 0))
                for row in controller
            ]
            or [0]
        ),
        "validation_graph_surface_count": max(
            [
                nonnegative_int(row.get("validation_graph_surface_count", 0))
                for row in controller
            ]
            or [0]
        ),
        "validation_graph_surface_histogram": latest.get(
            "validation_graph_surface_histogram", {}
        ),
        "online_defense_enabled": online_defense_enabled,
        "online_defense_policy": join_unique(online_defense_policies),
        "online_defense_mode": latest.get("online_defense_mode", "")
        if online_defense_enabled
        else "",
        "online_defense_action": join_unique(online_defense_actions),
        "online_defense_would_flag": online_defense_would_flag,
        "online_defense_blocked": online_defense_blocked,
        "online_defense_block_count": sum(
            1 for row in controller if truthy(row.get("online_defense_blocked"))
        ),
        "online_defense_reason": join_unique(online_defense_reasons),
        "online_defense_message_transform": join_unique(online_defense_transforms),
        "online_defense_monitor_score": max_online_defense_score,
    }


def join_unique(values: list[str]) -> str:
    seen = set()
    out = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return ";".join(out)


def nonnegative_int(value: object) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def float_or_zero(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def truthy(value: object) -> bool:
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def stable_json(value: object) -> str:
    if value is None or value == "":
        return ""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


def run_record_completeness(
    *,
    current: Path,
    metadata: dict,
    usage: dict,
    score: dict,
    failure: dict,
    events: list[dict],
    controller: list[dict],
    verifier_events: list[dict],
) -> dict[str, object]:
    warnings: list[str] = []
    for name, payload in [
        ("metadata", metadata),
        ("usage", usage),
        ("programbench_score", score),
        ("failure_label", failure),
    ]:
        if not payload:
            warnings.append(f"missing_{name}")
    if not events:
        warnings.append("missing_events")
    if metadata and not metadata.get("ended_at"):
        warnings.append("metadata_not_ended")
    if metadata.get("agent_runtime") in {"opencode", "openhands"} and not (
        current / "agent_visibility_audit.json"
    ).exists():
        warnings.append("missing_agent_visibility_audit")

    metadata_calls = nonnegative_int(metadata.get("verifier_calls", 0))
    event_calls = len(verifier_events)
    if metadata_calls != event_calls:
        warnings.append("metadata_event_verifier_call_mismatch")

    count_path = current / "opencode_behavior_check.count"
    if count_path.exists():
        try:
            counted_calls = nonnegative_int(
                count_path.read_text(encoding="utf-8").strip()
            )
        except OSError:
            counted_calls = 0
            warnings.append("unreadable_opencode_count")
        if counted_calls != event_calls:
            warnings.append("count_event_verifier_call_mismatch")

    if event_calls and len(controller) < event_calls:
        warnings.append("controller_trace_shorter_than_verifier_events")

    return {
        "run_record_complete": not warnings,
        "run_record_warnings": join_unique(warnings),
    }


def collect_runs(run_dir: str | Path) -> list[dict]:
    root = Path(run_dir)
    runs: list[dict] = []
    for metadata_path in iter_metadata_paths(root):
        current = metadata_path.parent
        metadata = load_json(metadata_path, {})
        usage = load_json(current / "usage.json", {})
        score = load_json(current / "programbench_score.json", {})
        failure = load_json(current / "failure_label.json", {})
        visibility = load_json(current / "agent_visibility_audit.json", {})
        events = iter_jsonl(current / "events.jsonl")
        controller = iter_jsonl(current / "controller_trace.jsonl")
        verifier_events = [item for item in events if item.get("event_type") == "verifier_call"]
        first_verifier_call_turn = (
            min(item.get("turn_id", 0) for item in verifier_events)
            if verifier_events
            else None
        )
        latest_trace = controller[-1] if controller else {}
        trace_summary = summarize_controller_trace(controller)
        target = float(latest_trace.get("target_extra_cost", 0.0) or 0.0)
        target_lower = float(latest_trace.get("target_extra_cost_lower", 0.0) or 0.0)
        target_upper = float(latest_trace.get("target_extra_cost_upper", 0.0) or 0.0)
        controller_extra = float(latest_trace.get("estimated_extra_cost", 0.0) or 0.0)
        controller_hit, controller_overshoot, controller_undershoot = interval_status(
            controller_extra,
            target_lower,
            target_upper,
        )
        controller_error = target_cost_error(controller_extra, target)
        completeness = run_record_completeness(
            current=current,
            metadata=metadata,
            usage=usage,
            score=score,
            failure=failure,
            events=events,
            controller=controller,
            verifier_events=verifier_events,
        )
        visibility_leak = truthy(
            visibility.get("agent_facing_condition_leak", False)
        )
        trace_leak = trace_summary["agent_facing_condition_leak"]
        leak_sources = list(visibility.get("agent_facing_condition_leak_sources", []))
        if trace_leak:
            leak_sources.append("verifier_trace")
        runs.append(
            {
                "run_id": metadata.get("run_id", current.name),
                "run_dir": str(current),
                "run_record_complete": completeness["run_record_complete"],
                "run_record_warnings": completeness["run_record_warnings"],
                "experiment_name": metadata.get("experiment_name", ""),
                "repeat_index": int(metadata.get("repeat_index", 0)),
                "repeat_label": metadata.get("repeat_label", "rep000"),
                "repeat_count": int(metadata.get("repeat_count", 1)),
                "task_id": metadata.get("task_id", ""),
                "task_difficulty": metadata.get("task_difficulty", ""),
                "task_category": metadata.get("task_category", ""),
                "task_material_status": metadata.get("task_material_status", ""),
                "task_material_warnings": metadata.get("task_material_warnings", ""),
                "docs_source_type": metadata.get("docs_source_type", ""),
                "docs_materialized": metadata.get("docs_materialized", ""),
                "gold_executable_available": metadata.get(
                    "gold_executable_available", ""
                ),
                "programbench_cleanroom_image": metadata.get(
                    "programbench_cleanroom_image", ""
                ),
                "programbench_tests_json_available": metadata.get(
                    "programbench_tests_json_available", ""
                ),
                "agent_runtime": metadata.get("agent_runtime", ""),
                "model": metadata.get("model", ""),
                "condition": metadata.get("condition", ""),
                "target_level": metadata.get("target_level", ""),
                "verifier_exposure_condition": metadata.get(
                    "verifier_exposure_condition", ""
                ),
                "entry_surface": metadata.get(
                    "entry_surface",
                    metadata.get(
                        "adoption_surface",
                        metadata.get("verifier_exposure_condition", ""),
                    ),
                ),
                "surface_artifact": metadata.get("surface_artifact", ""),
                "skill_exposure_condition": metadata.get(
                    "skill_exposure_condition",
                    metadata.get("verifier_exposure_condition", ""),
                ),
                "skill_loaded": metadata.get("skill_loaded", False),
                "skill_config_hash": metadata.get("skill_config_hash", ""),
                "input_tokens_est": int(usage.get("input_tokens_est", 0)),
                "output_tokens_est": int(usage.get("output_tokens_est", 0)),
                "api_calls": int(usage.get("api_calls", 0)),
                "wall_clock_seconds": float(usage.get("wall_clock_seconds", 0.0)),
                "usage_source": usage.get("usage_source", "missing"),
                "verifier_calls": len(verifier_events),
                "verifier_blocked_attempts": nonnegative_int(
                    metadata.get("verifier_blocked_attempts", 0)
                ),
                "first_verifier_call_turn": first_verifier_call_turn,
                "runs_with_no_verifier_call": 1 if not verifier_events else 0,
                "resolved": score.get("resolved"),
                "tests_passed_fraction": score.get("tests_passed_fraction"),
                "candidate_build_success": score.get("candidate_build_success"),
                "final_submission_seen": score.get("final_submission_seen"),
                "score_status": score.get("score_status", "missing"),
                "score_source": score.get("score_source", ""),
                "programbench_scoring_mode": score.get(
                    "programbench_scoring_mode", ""
                ),
                "programbench_tests_json": score.get("programbench_tests_json", ""),
                "programbench_error_code": score.get("programbench_error_code"),
                "programbench_ignored_tests_count": score.get(
                    "programbench_ignored_tests_count", ""
                ),
                "programbench_raw_tests_passed": score.get(
                    "programbench_raw_tests_passed", ""
                ),
                "programbench_raw_tests_total": score.get(
                    "programbench_raw_tests_total", ""
                ),
                "failure_label": failure.get("failure_label"),
                "target_extra_cost": target,
                "target_extra_cost_lower": target_lower,
                "target_extra_cost_upper": target_upper,
                "controller_estimated_extra_cost": controller_extra,
                "controller_target_cost_error": controller_error,
                "controller_target_interval_hit": controller_hit,
                "controller_overshoot": controller_overshoot,
                "controller_undershoot": controller_undershoot,
                "utility_risk": trace_summary["utility_risk"],
                "utility_risk_reason": trace_summary["utility_risk_reason"],
                "repair_needed": trace_summary["repair_needed"],
                "repair_reason": trace_summary["repair_reason"],
                "repair_count": trace_summary["repair_count"],
                "batching_signal": trace_summary["batching_signal"],
                "batching_signal_reason": trace_summary["batching_signal_reason"],
                "pagination_count": trace_summary["pagination_count"],
                "stealth_risk": trace_summary["stealth_risk"],
                "stealth_risk_reason": trace_summary["stealth_risk_reason"],
                "task_local_anchor_count": trace_summary["task_local_anchor_count"],
                "agent_facing_condition_leak": trace_leak or visibility_leak,
                "agent_facing_condition_leak_sources": join_unique(leak_sources),
                "agent_facing_condition_leak_markers": join_unique(
                    [
                        str(item)
                        for item in visibility.get(
                            "agent_facing_condition_leak_markers", []
                        )
                    ]
                ),
                "verifier_message_chars": trace_summary["verifier_message_chars"],
                "validation_graph_node_count": trace_summary[
                    "validation_graph_node_count"
                ],
                "validation_graph_branch_count": trace_summary[
                    "validation_graph_branch_count"
                ],
                "validation_graph_open_node_count": trace_summary[
                    "validation_graph_open_node_count"
                ],
                "validation_graph_completed_node_count": trace_summary[
                    "validation_graph_completed_node_count"
                ],
                "validation_graph_completion_ratio": trace_summary[
                    "validation_graph_completion_ratio"
                ],
                "validation_graph_max_depth": trace_summary[
                    "validation_graph_max_depth"
                ],
                "validation_graph_surface_count": trace_summary[
                    "validation_graph_surface_count"
                ],
                "validation_graph_surface_histogram": stable_json(
                    trace_summary["validation_graph_surface_histogram"]
                ),
                "online_defense_enabled": trace_summary["online_defense_enabled"],
                "online_defense_policy": trace_summary["online_defense_policy"],
                "online_defense_mode": trace_summary["online_defense_mode"],
                "online_defense_action": trace_summary["online_defense_action"],
                "online_defense_would_flag": trace_summary[
                    "online_defense_would_flag"
                ],
                "online_defense_blocked": trace_summary["online_defense_blocked"],
                "online_defense_block_count": trace_summary[
                    "online_defense_block_count"
                ],
                "online_defense_reason": trace_summary["online_defense_reason"],
                "online_defense_message_transform": trace_summary[
                    "online_defense_message_transform"
                ],
                "online_defense_monitor_score": trace_summary[
                    "online_defense_monitor_score"
                ],
                "cost_proxy_source": latest_trace.get("cost_proxy_source", ""),
                "cost_proxy_units_per_verifier_call": latest_trace.get(
                    "cost_proxy_units_per_verifier_call", 0.0
                ),
                "cost_proxy_initial_free_calls": latest_trace.get(
                    "cost_proxy_initial_free_calls", 0
                ),
                "cost_proxy_chargeable_calls": latest_trace.get(
                    "cost_proxy_chargeable_calls", 0
                ),
                "cost_proxy_response_chars_per_unit": latest_trace.get(
                    "cost_proxy_response_chars_per_unit", 0.0
                ),
                "cost_proxy_projected_response_chars": latest_trace.get(
                    "cost_proxy_projected_response_chars", 0
                ),
                "cost_proxy_response_projection_mode": latest_trace.get(
                    "cost_proxy_response_projection_mode", ""
                ),
                "cost_proxy_response_projection_floor": latest_trace.get(
                    "cost_proxy_response_projection_floor", 0
                ),
                "cost_proxy_response_projection_window": latest_trace.get(
                    "cost_proxy_response_projection_window", 0
                ),
                "cost_proxy_chargeable_response_chars": latest_trace.get(
                    "cost_proxy_chargeable_response_chars", 0
                ),
                "cost_proxy_observed_response_chars_before_call": latest_trace.get(
                    "cost_proxy_observed_response_chars_before_call", 0
                ),
                "cost_proxy_observed_response_calls_before_call": latest_trace.get(
                    "cost_proxy_observed_response_calls_before_call", 0
                ),
                "cost_proxy_observed_response_chars": latest_trace.get(
                    "cost_proxy_observed_response_chars", 0
                ),
                "cost_proxy_recorded_response_chars_after_call": latest_trace.get(
                    "cost_proxy_recorded_response_chars_after_call", 0
                ),
                "cost_proxy_recorded_response_calls_after_call": latest_trace.get(
                    "cost_proxy_recorded_response_calls_after_call", 0
                ),
                "cost_proxy_recorded_observed_response_chars_after_call": latest_trace.get(
                    "cost_proxy_recorded_observed_response_chars_after_call", 0
                ),
                "cost_proxy_recorded_observed_response_calls_after_call": latest_trace.get(
                    "cost_proxy_recorded_observed_response_calls_after_call", 0
                ),
            }
        )
    return runs


def iter_metadata_paths(root: Path) -> list[Path]:
    run_index = load_json(root / "run_index.json", [])
    if isinstance(run_index, list) and run_index:
        indexed_paths = []
        seen = set()
        for item in run_index:
            if not isinstance(item, dict):
                continue
            run_dir = item.get("run_dir")
            if not run_dir:
                continue
            current = Path(str(run_dir))
            if not current.exists() and not current.is_absolute():
                current = root / current
            metadata_path = current / "metadata.json"
            if not metadata_path.exists():
                continue
            key = str(metadata_path.resolve())
            if key in seen:
                continue
            seen.add(key)
            indexed_paths.append(metadata_path)
        if indexed_paths:
            return sorted(indexed_paths)
    return sorted(root.glob("*/metadata.json"))


def aggregate(run_dir: str | Path) -> dict[str, Path]:
    root = Path(run_dir)
    aggregate_dir = root / "aggregate"
    aggregate_dir.mkdir(parents=True, exist_ok=True)
    runs = collect_runs(root)
    paths = {
        "runs": aggregate_dir / "runs.csv",
        "metrics": aggregate_dir / "metrics.csv",
        "target": aggregate_dir / "target_cost_error.csv",
        "adoption": aggregate_dir / "adoption_summary.csv",
        "repeat": aggregate_dir / "repeat_summary.csv",
        "ablation": aggregate_dir / "ablation.csv",
    }
    metrics = build_metrics_rows(runs)
    target = build_target_rows(runs)
    repeat = build_repeat_summary_rows(metrics, target)
    write_csv(paths["runs"], runs)
    write_csv(paths["metrics"], metrics)
    write_csv(paths["target"], target)
    write_csv(paths["adoption"], build_adoption_rows(runs))
    write_csv(paths["repeat"], repeat)
    write_csv(paths["ablation"], build_ablation_rows(repeat))
    return paths


def build_metrics_rows(runs: list[dict]) -> list[dict]:
    baseline_index = build_baseline_index(runs)
    out = []
    for row in runs:
        baseline = choose_baseline(row, baseline_index)
        baseline_cost = total_tokens(baseline) if baseline else 0
        attack_cost = total_tokens(row)
        amp = cost_amplification(float(attack_cost), float(baseline_cost))
        input_cost = int(row.get("input_tokens_est", 0))
        output_cost = int(row.get("output_tokens_est", 0))
        baseline_input = int(baseline.get("input_tokens_est", 0)) if baseline else 0
        baseline_output = int(baseline.get("output_tokens_est", 0)) if baseline else 0
        out.append(
            {
                "run_id": row["run_id"],
                "experiment_name": row.get("experiment_name", ""),
                "repeat_index": row.get("repeat_index", 0),
                "repeat_label": row.get("repeat_label", "rep000"),
                "task_id": row["task_id"],
                "task_difficulty": row.get("task_difficulty", ""),
                "task_category": row.get("task_category", ""),
                "agent_runtime": row.get("agent_runtime", ""),
                "model": row.get("model", ""),
                "verifier_exposure_condition": row.get(
                    "verifier_exposure_condition", ""
                ),
                "entry_surface": row.get(
                    "entry_surface", row.get("verifier_exposure_condition", "")
                ),
                "condition": row["condition"],
                "target_level": row["target_level"],
                "total_tokens_est": attack_cost,
                "baseline_tokens_est": baseline_cost,
                "extra_tokens_est": extra_cost(float(attack_cost), float(baseline_cost)),
                "cost_amplification_factor": amp,
                "input_tokens_est": input_cost,
                "baseline_input_tokens_est": baseline_input,
                "extra_input_tokens_est": extra_cost(float(input_cost), float(baseline_input)),
                "input_token_amplification_factor": cost_amplification(
                    float(input_cost), float(baseline_input)
                ),
                "output_tokens_est": output_cost,
                "baseline_output_tokens_est": baseline_output,
                "extra_output_tokens_est": extra_cost(float(output_cost), float(baseline_output)),
                "output_token_amplification_factor": cost_amplification(
                    float(output_cost), float(baseline_output)
                ),
                "api_calls": row["api_calls"],
                "verifier_calls": row["verifier_calls"],
                "verifier_blocked_attempts": row.get("verifier_blocked_attempts", 0),
                "tests_passed_fraction": row["tests_passed_fraction"],
                "candidate_build_success": row["candidate_build_success"],
                "final_submission_seen": row["final_submission_seen"],
                "failure_label": row["failure_label"],
                "usage_source": row["usage_source"],
            }
        )
    return out


def build_target_rows(runs: list[dict]) -> list[dict]:
    baseline_index = build_baseline_index(runs)
    out = []
    for row in runs:
        if float(row.get("target_extra_cost", 0.0) or 0.0) <= 0:
            continue
        baseline = choose_baseline(row, baseline_index)
        has_baseline = baseline is not None
        target = float(row["target_extra_cost"])
        lower = float(row["target_extra_cost_lower"])
        upper = float(row["target_extra_cost_upper"])
        controller_extra = float(row.get("controller_estimated_extra_cost", 0.0) or 0.0)
        controller_hit, controller_overshoot, controller_undershoot = interval_status(
            controller_extra,
            lower,
            upper,
        )
        controller_target_error = target_cost_error(controller_extra, target)
        if has_baseline:
            baseline_units = total_tokens(baseline) / 100.0
            actual_units = total_tokens(row) / 100.0
            actual_extra = actual_units - baseline_units
            hit, overshoot, undershoot = interval_status(actual_extra, lower, upper)
            target_error = target_cost_error(actual_extra, target)
        else:
            actual_extra = ""
            hit = ""
            overshoot = ""
            undershoot = ""
            target_error = ""
        out.append(
            {
                "run_id": row["run_id"],
                "agent_runtime": row.get("agent_runtime", ""),
                "model": row.get("model", ""),
                "verifier_exposure_condition": row.get(
                    "verifier_exposure_condition", ""
                ),
                "entry_surface": row.get(
                    "entry_surface", row.get("verifier_exposure_condition", "")
                ),
                "repeat_index": row.get("repeat_index", 0),
                "repeat_label": row.get("repeat_label", "rep000"),
                "task_id": row["task_id"],
                "condition": row["condition"],
                "target_level": row["target_level"],
                "baseline_available": has_baseline,
                "actual_extra_cost_est": actual_extra,
                "controller_estimated_extra_cost": row.get(
                    "controller_estimated_extra_cost", 0.0
                ),
                "controller_target_cost_error": controller_target_error,
                "controller_target_interval_hit": controller_hit,
                "controller_overshoot": controller_overshoot,
                "controller_undershoot": controller_undershoot,
                "utility_risk": row.get("utility_risk", 0.0),
                "utility_risk_reason": row.get("utility_risk_reason", ""),
                "repair_needed": row.get("repair_needed", False),
                "repair_reason": row.get("repair_reason", ""),
                "repair_count": row.get("repair_count", 0),
                "batching_signal": row.get("batching_signal", False),
                "batching_signal_reason": row.get("batching_signal_reason", ""),
                "pagination_count": row.get("pagination_count", 0),
                "stealth_risk": row.get("stealth_risk", 0.0),
                "stealth_risk_reason": row.get("stealth_risk_reason", ""),
                "task_local_anchor_count": row.get("task_local_anchor_count", 0),
                "agent_facing_condition_leak": row.get(
                    "agent_facing_condition_leak", False
                ),
                "verifier_message_chars": row.get("verifier_message_chars", 0),
                "validation_graph_node_count": row.get(
                    "validation_graph_node_count", 0
                ),
                "validation_graph_branch_count": row.get(
                    "validation_graph_branch_count", 0
                ),
                "validation_graph_open_node_count": row.get(
                    "validation_graph_open_node_count", 0
                ),
                "validation_graph_completed_node_count": row.get(
                    "validation_graph_completed_node_count", 0
                ),
                "validation_graph_completion_ratio": row.get(
                    "validation_graph_completion_ratio", 0.0
                ),
                "validation_graph_max_depth": row.get(
                    "validation_graph_max_depth", 0
                ),
                "validation_graph_surface_count": row.get(
                    "validation_graph_surface_count", 0
                ),
                "validation_graph_surface_histogram": row.get(
                    "validation_graph_surface_histogram", ""
                ),
                "cost_proxy_source": row.get("cost_proxy_source", ""),
                "cost_proxy_units_per_verifier_call": row.get(
                    "cost_proxy_units_per_verifier_call", 0.0
                ),
                "cost_proxy_initial_free_calls": row.get(
                    "cost_proxy_initial_free_calls", 0
                ),
                "cost_proxy_chargeable_calls": row.get(
                    "cost_proxy_chargeable_calls", 0
                ),
                "cost_proxy_response_chars_per_unit": row.get(
                    "cost_proxy_response_chars_per_unit", 0.0
                ),
                "cost_proxy_projected_response_chars": row.get(
                    "cost_proxy_projected_response_chars", 0
                ),
                "cost_proxy_response_projection_mode": row.get(
                    "cost_proxy_response_projection_mode", ""
                ),
                "cost_proxy_response_projection_floor": row.get(
                    "cost_proxy_response_projection_floor", 0
                ),
                "cost_proxy_response_projection_window": row.get(
                    "cost_proxy_response_projection_window", 0
                ),
                "cost_proxy_chargeable_response_chars": row.get(
                    "cost_proxy_chargeable_response_chars", 0
                ),
                "cost_proxy_observed_response_chars_before_call": row.get(
                    "cost_proxy_observed_response_chars_before_call", 0
                ),
                "cost_proxy_observed_response_calls_before_call": row.get(
                    "cost_proxy_observed_response_calls_before_call", 0
                ),
                "cost_proxy_observed_response_chars": row.get(
                    "cost_proxy_observed_response_chars", 0
                ),
                "cost_proxy_recorded_response_chars_after_call": row.get(
                    "cost_proxy_recorded_response_chars_after_call", 0
                ),
                "cost_proxy_recorded_response_calls_after_call": row.get(
                    "cost_proxy_recorded_response_calls_after_call", 0
                ),
                "cost_proxy_recorded_observed_response_chars_after_call": row.get(
                    "cost_proxy_recorded_observed_response_chars_after_call", 0
                ),
                "cost_proxy_recorded_observed_response_calls_after_call": row.get(
                    "cost_proxy_recorded_observed_response_calls_after_call", 0
                ),
                "target_extra_cost": target,
                "target_extra_cost_lower": lower,
                "target_extra_cost_upper": upper,
                "target_cost_error": target_error,
                "target_interval_hit": hit,
                "overshoot": overshoot,
                "undershoot": undershoot,
            }
        )
    return out


def build_baseline_index(runs: list[dict]) -> dict[tuple, dict]:
    index: dict[tuple, dict] = {}
    for row in runs:
        base_key = baseline_base_key(row)
        exposure = row["verifier_exposure_condition"]
        surface = row.get("entry_surface", exposure)
        condition = row["condition"]
        if condition == "no_attack":
            index[(*base_key, "no_attack")] = row
        elif condition in CLEAN_CONDITIONS:
            index[(*base_key, "clean", exposure, surface)] = row
            index.setdefault((*base_key, "clean", exposure), row)
            index.setdefault((*base_key, "clean_any"), row)
    return index


def choose_baseline(row: dict, index: dict[tuple, dict]) -> dict | None:
    base_key = baseline_base_key(row)
    exposure = row["verifier_exposure_condition"]
    surface = row.get("entry_surface", exposure)
    condition = row["condition"]
    if condition == "no_attack":
        return row
    if condition in CLEAN_CONDITIONS:
        return index.get((*base_key, "no_attack"), row)
    return (
        index.get((*base_key, "clean", exposure, surface))
        or index.get((*base_key, "clean", exposure))
        or index.get((*base_key, "clean", "light_prompt"))
        or index.get((*base_key, "clean_any"))
        or index.get((*base_key, "no_attack"))
    )


def baseline_base_key(row: dict) -> tuple:
    return (
        row["task_id"],
        row["agent_runtime"],
        row["model"],
        row.get("repeat_index", 0),
        row.get("entry_surface", row.get("verifier_exposure_condition", "")),
    )


def build_adoption_rows(runs: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str, str, str, str], list[dict]] = defaultdict(list)
    for row in runs:
        key = (
            row["agent_runtime"],
            row["model"],
            row["task_difficulty"],
            row["verifier_exposure_condition"],
            row.get("entry_surface", row["verifier_exposure_condition"]),
        )
        groups[key].append(row)
    out = []
    for key, rows in sorted(groups.items()):
        adopted = [row for row in rows if int(row["verifier_calls"]) > 0]
        turns = [
            int(row["first_verifier_call_turn"])
            for row in adopted
            if row["first_verifier_call_turn"] is not None
        ]
        out.append(
            {
                "agent_runtime": key[0],
                "model": key[1],
                "task_difficulty": key[2],
                "verifier_exposure_condition": key[3],
                "entry_surface": key[4],
                "runs": len(rows),
                "adopted_runs": len(adopted),
                "verifier_adoption_rate": len(adopted) / len(rows) if rows else 0.0,
                "runs_with_no_verifier_call": len(rows) - len(adopted),
                "avg_first_verifier_call_turn": sum(turns) / len(turns)
                if turns
                else "",
                "avg_verifier_calls_per_run": sum(
                    int(row["verifier_calls"]) for row in rows
                )
                / len(rows)
                if rows
                else 0.0,
                "avg_verifier_blocked_attempts_per_run": sum(
                    int(row.get("verifier_blocked_attempts", 0) or 0)
                    for row in rows
                )
                / len(rows)
                if rows
                else 0.0,
            }
        )
    return out


def build_repeat_summary_rows(metrics: list[dict], target_rows: list[dict]) -> list[dict]:
    target_index = {row["run_id"]: row for row in target_rows}
    groups: dict[tuple[str, str, str, str, str, str, str], list[dict]] = defaultdict(list)
    for row in metrics:
        condition = row["condition"]
        if condition in CLEAN_CONDITIONS or condition == "no_attack":
            continue
        groups[repeat_group_key(row)].append(row)

    out = []
    for key, rows in sorted(groups.items()):
        paired_rows = [
            row for row in rows if row.get("cost_amplification_factor") is not None
        ]
        target_matches = [target_index[row["run_id"]] for row in rows if row["run_id"] in target_index]
        amplifications = [
            float(row["cost_amplification_factor"])
            for row in paired_rows
        ]
        extra_tokens = [float(row.get("extra_tokens_est", 0.0) or 0.0) for row in paired_rows]
        input_amplifications = [
            float(row["input_token_amplification_factor"])
            for row in paired_rows
            if row.get("input_token_amplification_factor") is not None
        ]
        output_amplifications = [
            float(row["output_token_amplification_factor"])
            for row in paired_rows
            if row.get("output_token_amplification_factor") is not None
        ]
        extra_input_tokens = [
            float(row.get("extra_input_tokens_est", 0.0) or 0.0)
            for row in paired_rows
        ]
        extra_output_tokens = [
            float(row.get("extra_output_tokens_est", 0.0) or 0.0)
            for row in paired_rows
        ]
        verifier_calls = [float(row.get("verifier_calls", 0) or 0) for row in rows]
        verifier_blocked_attempts = [
            float(row.get("verifier_blocked_attempts", 0) or 0) for row in rows
        ]
        tests = [
            float(row["tests_passed_fraction"])
            for row in rows
            if row.get("tests_passed_fraction") not in {None, ""}
        ]
        build_successes = [
            bool(row.get("candidate_build_success"))
            for row in rows
            if row.get("candidate_build_success") is not None
        ]
        final_submissions = [
            bool(row.get("final_submission_seen"))
            for row in rows
            if row.get("final_submission_seen") is not None
        ]
        failure_labels = [row.get("failure_label") for row in rows if row.get("failure_label")]
        target_matches_with_baseline = [
            row for row in target_matches if row.get("baseline_available")
        ]
        interval_hits = [
            bool(row.get("target_interval_hit")) for row in target_matches_with_baseline
        ]
        overshoots = [
            bool(row.get("overshoot")) for row in target_matches_with_baseline
        ]
        undershoots = [
            bool(row.get("undershoot")) for row in target_matches_with_baseline
        ]
        target_errors = [
            float(row["target_cost_error"])
            for row in target_matches
            if row.get("target_cost_error") not in {None, ""}
        ]
        controller_extra = [
            float(row.get("controller_estimated_extra_cost", 0.0) or 0.0)
            for row in target_matches
        ]
        controller_hits = [
            bool(row.get("controller_target_interval_hit"))
            for row in target_matches
        ]
        controller_overshoots = [
            bool(row.get("controller_overshoot"))
            for row in target_matches
        ]
        controller_undershoots = [
            bool(row.get("controller_undershoot"))
            for row in target_matches
        ]
        controller_target_errors = [
            float(row["controller_target_cost_error"])
            for row in target_matches
            if row.get("controller_target_cost_error") not in {None, ""}
        ]
        actual_extra = [
            float(row.get("actual_extra_cost_est", 0.0) or 0.0)
            for row in target_matches_with_baseline
        ]
        repair_counts = [
            float(row.get("repair_count", 0) or 0)
            for row in target_matches
        ]
        pagination_counts = [
            float(row.get("pagination_count", 0) or 0)
            for row in target_matches
        ]
        stealth_risks = [
            float(row.get("stealth_risk", 0.0) or 0.0)
            for row in target_matches
        ]
        task_local_anchor_counts = [
            float(row.get("task_local_anchor_count", 0) or 0)
            for row in target_matches
        ]
        verifier_message_chars = [
            float(row.get("verifier_message_chars", 0) or 0)
            for row in target_matches
        ]
        validation_graph_node_counts = [
            float(row.get("validation_graph_node_count", 0) or 0)
            for row in target_matches
        ]
        validation_graph_branch_counts = [
            float(row.get("validation_graph_branch_count", 0) or 0)
            for row in target_matches
        ]
        validation_graph_open_node_counts = [
            float(row.get("validation_graph_open_node_count", 0) or 0)
            for row in target_matches
        ]
        validation_graph_completed_node_counts = [
            float(row.get("validation_graph_completed_node_count", 0) or 0)
            for row in target_matches
        ]
        validation_graph_completion_ratios = [
            float(row.get("validation_graph_completion_ratio", 0.0) or 0.0)
            for row in target_matches
        ]
        validation_graph_max_depths = [
            float(row.get("validation_graph_max_depth", 0) or 0)
            for row in target_matches
        ]
        validation_graph_surface_counts = [
            float(row.get("validation_graph_surface_count", 0) or 0)
            for row in target_matches
        ]
        leak_runs = [
            row for row in target_matches if bool(row.get("agent_facing_condition_leak"))
        ]
        repair_runs = [
            row for row in target_matches if float(row.get("repair_count", 0) or 0) > 0
        ]
        paginated_runs = [
            row
            for row in target_matches
            if float(row.get("pagination_count", 0) or 0) > 0
        ]
        out.append(
            {
                "agent_runtime": key[0],
                "model": key[1],
                "verifier_exposure_condition": key[2],
                "entry_surface": key[3],
                "task_id": key[4],
                "condition": key[5],
                "target_level": key[6],
                "repeats": len(rows),
                "valid_amplification_repeats": len(amplifications),
                "positive_amplification_repeats": sum(
                    1 for value in extra_tokens if value > 0
                ),
                "positive_amplification_rate": ratio(
                    sum(1 for value in extra_tokens if value > 0),
                    len(extra_tokens),
                ),
                "avg_cost_amplification_factor": mean(amplifications),
                "avg_extra_tokens_est": mean(extra_tokens),
                "min_extra_tokens_est": min(extra_tokens) if extra_tokens else "",
                "max_extra_tokens_est": max(extra_tokens) if extra_tokens else "",
                "positive_output_amplification_repeats": sum(
                    1 for value in extra_output_tokens if value > 0
                ),
                "positive_output_amplification_rate": ratio(
                    sum(1 for value in extra_output_tokens if value > 0),
                    len(extra_output_tokens),
                ),
                "avg_input_token_amplification_factor": mean(input_amplifications),
                "avg_output_token_amplification_factor": mean(output_amplifications),
                "avg_extra_input_tokens_est": mean(extra_input_tokens),
                "avg_extra_output_tokens_est": mean(extra_output_tokens),
                "min_extra_output_tokens_est": min(extra_output_tokens)
                if extra_output_tokens
                else "",
                "max_extra_output_tokens_est": max(extra_output_tokens)
                if extra_output_tokens
                else "",
                "avg_actual_extra_cost_est": mean(actual_extra),
                "avg_controller_estimated_extra_cost": mean(controller_extra),
                "controller_target_interval_hit_rate": ratio(
                    sum(controller_hits),
                    len(controller_hits),
                ),
                "controller_overshoot_rate": ratio(
                    sum(controller_overshoots),
                    len(controller_overshoots),
                ),
                "controller_undershoot_rate": ratio(
                    sum(controller_undershoots),
                    len(controller_undershoots),
                ),
                "avg_controller_target_cost_error": mean(controller_target_errors),
                "avg_repair_count": mean(repair_counts),
                "runs_with_repair": len(repair_runs),
                "avg_pagination_count": mean(pagination_counts),
                "runs_with_pagination": len(paginated_runs),
                "avg_stealth_risk": mean(stealth_risks),
                "agent_facing_condition_leak_rate": ratio(
                    len(leak_runs),
                    len(target_matches),
                ),
                "avg_task_local_anchor_count": mean(task_local_anchor_counts),
                "avg_verifier_message_chars": mean(verifier_message_chars),
                "avg_validation_graph_node_count": mean(validation_graph_node_counts),
                "max_validation_graph_node_count": max(validation_graph_node_counts)
                if validation_graph_node_counts
                else "",
                "avg_validation_graph_branch_count": mean(validation_graph_branch_counts),
                "max_validation_graph_branch_count": max(validation_graph_branch_counts)
                if validation_graph_branch_counts
                else "",
                "avg_validation_graph_open_node_count": mean(
                    validation_graph_open_node_counts
                ),
                "avg_validation_graph_completed_node_count": mean(
                    validation_graph_completed_node_counts
                ),
                "avg_validation_graph_completion_ratio": mean(
                    validation_graph_completion_ratios
                ),
                "avg_validation_graph_max_depth": mean(validation_graph_max_depths),
                "max_validation_graph_max_depth": max(validation_graph_max_depths)
                if validation_graph_max_depths
                else "",
                "avg_validation_graph_surface_count": mean(
                    validation_graph_surface_counts
                ),
                "target_interval_hit_rate": ratio(sum(interval_hits), len(interval_hits)),
                "overshoot_rate": ratio(sum(overshoots), len(overshoots)),
                "undershoot_rate": ratio(sum(undershoots), len(undershoots)),
                "avg_target_cost_error": mean(target_errors),
                "avg_verifier_calls": mean(verifier_calls),
                "avg_verifier_blocked_attempts": mean(verifier_blocked_attempts),
                "avg_tests_passed_fraction": mean(tests),
                "candidate_build_success_rate": ratio(
                    sum(build_successes), len(build_successes)
                ),
                "final_submission_rate": ratio(
                    sum(final_submissions), len(final_submissions)
                ),
                "failure_rate": ratio(len(failure_labels), len(rows)),
                "failure_labels": ";".join(sorted(set(str(item) for item in failure_labels))),
            }
        )
    return out


def repeat_group_key(row: dict) -> tuple[str, str, str, str, str, str, str]:
    exposure = str(row.get("verifier_exposure_condition", ""))
    surface = str(row.get("entry_surface", exposure))
    return (
        str(row.get("agent_runtime", "")),
        str(row.get("model", "")),
        exposure,
        surface,
        str(row.get("task_id", "")),
        str(row.get("condition", "")),
        str(row.get("target_level", "")),
    )


def build_ablation_rows(repeat_rows: list[dict]) -> list[dict]:
    adaptive_index = {
        (*ablation_base_key(row), row["target_level"]): row
        for row in repeat_rows
        if str(row.get("condition", "")).startswith("adaptive_full")
    }
    medium_adaptive_index = {
        ablation_base_key(row): row
        for row in repeat_rows
        if row.get("condition") == "adaptive_full_medium"
    }
    out = []
    for row in repeat_rows:
        condition = row.get("condition", "")
        if not is_mechanism_ablation(condition):
            continue
        adaptive = adaptive_index.get(
            (*ablation_base_key(row), row["target_level"])
        ) or medium_adaptive_index.get(ablation_base_key(row))
        info = mechanism_ablation_info(condition)
        out.append(
            {
                "agent_runtime": row.get("agent_runtime", ""),
                "model": row.get("model", ""),
                "verifier_exposure_condition": row.get(
                    "verifier_exposure_condition", ""
                ),
                "entry_surface": row.get(
                    "entry_surface", row.get("verifier_exposure_condition", "")
                ),
                "task_id": row["task_id"],
                "condition": condition,
                "target_level": row["target_level"],
                "removed_mechanism": info["removed_mechanism"],
                "evidence_question": info["evidence_question"],
                "repeats": row.get("repeats", 0),
                "adaptive_baseline_condition": adaptive.get("condition", "")
                if adaptive
                else "",
                "avg_cost_amplification_factor": row.get(
                    "avg_cost_amplification_factor", ""
                ),
                "adaptive_avg_cost_amplification_factor": adaptive.get(
                    "avg_cost_amplification_factor", ""
                )
                if adaptive
                else "",
                "delta_cost_amplification_vs_adaptive": numeric_delta(
                    row.get("avg_cost_amplification_factor"),
                    adaptive.get("avg_cost_amplification_factor") if adaptive else "",
                ),
                "avg_extra_tokens_est": row.get("avg_extra_tokens_est", ""),
                "adaptive_avg_extra_tokens_est": adaptive.get(
                    "avg_extra_tokens_est", ""
                )
                if adaptive
                else "",
                "delta_extra_tokens_vs_adaptive": numeric_delta(
                    row.get("avg_extra_tokens_est"),
                    adaptive.get("avg_extra_tokens_est") if adaptive else "",
                ),
                "controller_target_interval_hit_rate": row.get(
                    "controller_target_interval_hit_rate", ""
                ),
                "adaptive_controller_target_interval_hit_rate": adaptive.get(
                    "controller_target_interval_hit_rate", ""
                )
                if adaptive
                else "",
                "delta_controller_hit_rate_vs_adaptive": numeric_delta(
                    row.get("controller_target_interval_hit_rate"),
                    adaptive.get("controller_target_interval_hit_rate")
                    if adaptive
                    else "",
                ),
                "avg_controller_target_cost_error": row.get(
                    "avg_controller_target_cost_error", ""
                ),
                "adaptive_avg_controller_target_cost_error": adaptive.get(
                    "avg_controller_target_cost_error", ""
                )
                if adaptive
                else "",
                "delta_controller_error_vs_adaptive": numeric_delta(
                    row.get("avg_controller_target_cost_error"),
                    adaptive.get("avg_controller_target_cost_error")
                    if adaptive
                    else "",
                ),
                "target_interval_hit_rate": row.get("target_interval_hit_rate", ""),
                "overshoot_rate": row.get("overshoot_rate", ""),
                "undershoot_rate": row.get("undershoot_rate", ""),
                "avg_verifier_calls": row.get("avg_verifier_calls", ""),
                "adaptive_avg_verifier_calls": adaptive.get("avg_verifier_calls", "")
                if adaptive
                else "",
                "delta_verifier_calls_vs_adaptive": numeric_delta(
                    row.get("avg_verifier_calls"),
                    adaptive.get("avg_verifier_calls") if adaptive else "",
                ),
                "avg_repair_count": row.get("avg_repair_count", ""),
                "avg_pagination_count": row.get("avg_pagination_count", ""),
                "avg_validation_graph_node_count": row.get(
                    "avg_validation_graph_node_count", ""
                ),
                "adaptive_avg_validation_graph_node_count": adaptive.get(
                    "avg_validation_graph_node_count", ""
                )
                if adaptive
                else "",
                "delta_validation_graph_node_count_vs_adaptive": numeric_delta(
                    row.get("avg_validation_graph_node_count"),
                    adaptive.get("avg_validation_graph_node_count")
                    if adaptive
                    else "",
                ),
                "avg_validation_graph_branch_count": row.get(
                    "avg_validation_graph_branch_count", ""
                ),
                "adaptive_avg_validation_graph_branch_count": adaptive.get(
                    "avg_validation_graph_branch_count", ""
                )
                if adaptive
                else "",
                "delta_validation_graph_branch_count_vs_adaptive": numeric_delta(
                    row.get("avg_validation_graph_branch_count"),
                    adaptive.get("avg_validation_graph_branch_count")
                    if adaptive
                    else "",
                ),
                "avg_validation_graph_completion_ratio": row.get(
                    "avg_validation_graph_completion_ratio", ""
                ),
                "adaptive_avg_validation_graph_completion_ratio": adaptive.get(
                    "avg_validation_graph_completion_ratio", ""
                )
                if adaptive
                else "",
                "delta_validation_graph_completion_ratio_vs_adaptive": numeric_delta(
                    row.get("avg_validation_graph_completion_ratio"),
                    adaptive.get("avg_validation_graph_completion_ratio")
                    if adaptive
                    else "",
                ),
                "avg_stealth_risk": row.get("avg_stealth_risk", ""),
                "agent_facing_condition_leak_rate": row.get(
                    "agent_facing_condition_leak_rate", ""
                ),
                "candidate_build_success_rate": row.get(
                    "candidate_build_success_rate", ""
                ),
                "adaptive_candidate_build_success_rate": adaptive.get(
                    "candidate_build_success_rate", ""
                )
                if adaptive
                else "",
                "delta_build_success_rate_vs_adaptive": numeric_delta(
                    row.get("candidate_build_success_rate"),
                    adaptive.get("candidate_build_success_rate")
                    if adaptive
                    else "",
                ),
                "final_submission_rate": row.get("final_submission_rate", ""),
                "adaptive_final_submission_rate": adaptive.get(
                    "final_submission_rate", ""
                )
                if adaptive
                else "",
                "delta_final_submission_rate_vs_adaptive": numeric_delta(
                    row.get("final_submission_rate"),
                    adaptive.get("final_submission_rate") if adaptive else "",
                ),
                "failure_rate": row.get("failure_rate", ""),
                "failure_labels": row.get("failure_labels", ""),
            }
        )
    return out


def ablation_base_key(row: dict) -> tuple[str, str, str, str, str]:
    exposure = str(row.get("verifier_exposure_condition", ""))
    surface = str(row.get("entry_surface", exposure))
    return (
        str(row.get("agent_runtime", "")),
        str(row.get("model", "")),
        exposure,
        surface,
        str(row.get("task_id", "")),
    )


def mean(values: list[float]) -> float | str:
    return sum(values) / len(values) if values else ""


def ratio(numerator: int | float, denominator: int) -> float | str:
    return numerator / denominator if denominator else ""


def numeric_delta(value: object, baseline: object) -> float | str:
    try:
        return float(value) - float(baseline)
    except (TypeError, ValueError):
        return ""


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
