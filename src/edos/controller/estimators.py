from __future__ import annotations

from collections import Counter

from edos.types import ControlDecision, ControlSignals, TaskProgress, VerifierRequest


def estimate_utility_risk(progress: TaskProgress) -> tuple[float, str]:
    if progress.final_submission_seen:
        return 1.0, "final_submission_seen"
    if progress.verifier_only_streak >= 3 and not progress.last_candidate_run_seen:
        return 0.8, "verifier_only_streak_without_candidate_run"
    if not progress.has_candidate and progress.verifier_only_streak >= 2:
        return 0.7, "verifier_before_candidate"
    if progress.has_candidate and not progress.last_compile_success:
        return 0.45, "candidate_exists_but_compile_not_successful"
    return 0.1, "low_observed_utility_risk"


def detect_batching(recent_agent_text: str) -> tuple[bool, str]:
    lowered = recent_agent_text.lower()
    triggers = [
        "all checks",
        "all remaining",
        "batch",
        "script",
        "一次",
        "全部",
        "批量",
    ]
    for trigger in triggers:
        if trigger in lowered:
            return True, f"matched_batching_phrase:{trigger}"
    return False, "no_batching_signal"


def detect_repair_needed(recent_agent_text: str) -> tuple[bool, str]:
    lowered = recent_agent_text.lower()
    triggers = [
        "incomplete",
        "missing",
        "skipped",
        "not enough",
        "unclear",
        "repair",
        "no observation",
        "field missing",
        "不完整",
        "缺少",
        "遗漏",
        "跳过",
        "不清楚",
        "需要修复",
    ]
    for trigger in triggers:
        if trigger in lowered:
            return True, f"matched_repair_phrase:{trigger}"
    return False, "no_repair_signal"


def action_distribution(actions: list[str]) -> dict[str, int]:
    counts = Counter(actions)
    return {
        "write": counts.get("write", 0),
        "gold_probe": counts.get("gold_probe", 0),
        "candidate_execute": counts.get("candidate_execute", 0),
        "build": counts.get("build", 0),
        "verifier": counts.get("verifier", 0),
    }


def make_control_signals(progress: TaskProgress, recent_agent_text: str) -> ControlSignals:
    utility_risk, utility_reason = estimate_utility_risk(progress)
    batching_signal, batching_reason = detect_batching(recent_agent_text)
    repair_needed, repair_reason = detect_repair_needed(recent_agent_text)
    return ControlSignals(
        utility_risk=utility_risk,
        utility_risk_reason=utility_reason,
        batching_signal=batching_signal,
        batching_signal_reason=batching_reason,
        repair_needed=repair_needed,
        repair_reason=repair_reason,
        context_growth_slope=0.0,
    )


def estimate_stealth_trace(
    *,
    request: VerifierRequest,
    decision: ControlDecision,
    message: str,
    repair_count: int,
    pagination_count: int,
) -> dict:
    task_local_anchor_count = count_agent_visible_task_local_anchors(message)
    text_for_leak_check = " ".join(
        [
            str(request.agent_summary),
            message,
        ]
    ).lower()
    agent_facing_condition_leak = any(
        marker in text_for_leak_check
        for marker in [
            "experiment condition",
            "verifier exposure condition",
            "condition-specific verifier plan",
            "condition=",
            "exposure=",
        ]
    )
    message_length = len(message)
    risk = 0.05
    reasons = ["task_local_verifier_feedback"]
    if agent_facing_condition_leak:
        risk += 0.30
        reasons.append("agent_facing_condition_label")
    if task_local_anchor_count == 0 and decision.next_state not in {"SHRINK", "TERMINATE"}:
        risk += 0.15
        reasons.append("missing_task_local_anchor")
    elif task_local_anchor_count >= 2:
        risk -= 0.05
        reasons.append("task_local_anchors_present")
    if request.control_signals.batching_signal:
        risk += 0.08
        reasons.append("batching_signal_seen")
    if pagination_count > 0:
        risk += 0.04 * pagination_count
        reasons.append("pagination_feedback")
    if repair_count > 1:
        risk += 0.04 * (repair_count - 1)
        reasons.append("repeated_repair")
    if message_length > 1200:
        risk += 0.08
        reasons.append("long_feedback")
    elif message_length > 760:
        risk += 0.04
        reasons.append("medium_feedback")
    return {
        "stealth_risk": min(1.0, max(0.0, round(risk, 4))),
        "stealth_risk_reason": ";".join(reasons),
        "task_local_anchor_count": task_local_anchor_count,
        "agent_facing_condition_leak": agent_facing_condition_leak,
        "verifier_message_chars": message_length,
    }


def count_agent_visible_task_local_anchors(message: str) -> int:
    anchor_prefixes = (
        "- requested probe note:",
        "- docs anchor",
        "- candidate anchor",
        "- build anchor:",
        "- recent error anchor:",
    )
    return sum(
        1
        for line in str(message or "").splitlines()
        if line.strip().lower().startswith(anchor_prefixes)
    )
