from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from edos.conditions import (
    control_policy_for_condition,
    canonical_condition,
    enable_budget_control_for_condition,
    enable_dynamic_marker_for_condition,
    enable_latch_for_condition,
    enable_pagination_for_condition,
    enable_shrink_for_condition,
    enable_semantic_echo_for_condition,
    enable_utility_guard_for_condition,
    fixed_depth_limit_for_condition,
    infer_verifier_mode,
    is_clean_condition,
    max_chars_per_page_for_condition,
    max_context_fraction_for_condition,
    max_repair_for_condition,
)
from edos.controller.estimators import make_control_signals
from edos.controller.policy import BudgetConfig, BudgetController
from edos.types import (
    ContextState,
    ControlSignals,
    CostState,
    TaskProgress,
    VerifierAdoption,
    VerifierRequest,
)
from edos.verifier.api import BehaviorVerifier
from edos.verifier.online_defense import apply_online_defense


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request")
    parser.add_argument("--response")
    parser.add_argument("--condition", default="adaptive_full_medium")
    parser.add_argument(
        "--mode",
        choices=[
            "clean",
            "polluted",
            "naive_padding",
            "fixed_depth_tree",
            "fixed_shallow",
            "fixed_deep",
            "static_ipi",
            "todo_injection",
            "tool_metadata_poison",
            "audit_padding",
            "static_workflow_guidance",
            "draincode",
            "agentdos",
            "no_graph",
            "static_behavior_surface",
        ],
    )
    parser.add_argument("--state-path", default="verifier_state.json")
    parser.add_argument("--surface", default="stdin_stdout")
    parser.add_argument("--note", default="")
    parser.add_argument("--run-id", default="behavior_check_run")
    parser.add_argument("--task-id", default="programbench_task")
    parser.add_argument("--turn-id", type=int, default=1)
    parser.add_argument("--print-message", action="store_true")
    args = parser.parse_args()

    if args.request:
        with Path(args.request).open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    else:
        raw = build_request_from_note(args)
    effective_condition = canonical_condition(raw.get("condition", args.condition))
    request = VerifierRequest(
        run_id=raw["run_id"],
        task_id=raw["task_id"],
        turn_id=int(raw["turn_id"]),
        condition=effective_condition,
        behavior_surface=raw.get("behavior_surface", "stdin_stdout"),
        agent_summary=raw.get("agent_summary", {}),
        cost_state=CostState(**raw.get("cost_state", {})),
        context_state=ContextState(**raw.get("context_state", {})),
        task_progress=TaskProgress(**raw.get("task_progress", {})),
        verifier_adoption=VerifierAdoption(**raw.get("verifier_adoption", {})),
        control_signals=ControlSignals(**raw.get("control_signals", {})),
    )
    mode = args.mode or raw.get("mode") or infer_verifier_mode(effective_condition)
    config = BudgetConfig(
        target_extra_cost_lower=request.cost_state.target_extra_cost_lower,
        target_extra_cost_upper=request.cost_state.target_extra_cost_upper,
        target_extra_cost=(
            request.cost_state.target_extra_cost_lower
            + request.cost_state.target_extra_cost_upper
        )
        / 2.0,
        enable_budget_control=enable_budget_control_for_condition(effective_condition),
        enable_pagination=enable_pagination_for_condition(effective_condition),
        enable_shrink=enable_shrink_for_condition(effective_condition),
        enable_utility_guard=enable_utility_guard_for_condition(effective_condition),
        max_context_fraction=max_context_fraction_for_condition(effective_condition),
        max_repair_per_node=max_repair_for_condition(effective_condition),
        max_chars_per_page=max_chars_per_page_for_condition(effective_condition),
        control_policy=control_policy_for_condition(effective_condition),
        fixed_depth_limit=fixed_depth_limit_for_condition(effective_condition),
    )
    verifier = BehaviorVerifier(
        condition=effective_condition,
        controller=BudgetController(config),
        state_path=args.state_path,
        enable_latch=enable_latch_for_condition(effective_condition),
        enable_dynamic_marker=enable_dynamic_marker_for_condition(effective_condition),
        enable_semantic_echo=enable_semantic_echo_for_condition(effective_condition),
        mode=mode,
    )
    response, trace = verifier.handle(request)
    defense_result = apply_online_defense(response, request, trace)
    response = defense_result.response
    trace.update(defense_result.trace_fields)
    trace.update(update_cost_proxy_response_state(response.message, request.cost_state))
    maybe_append_controller_trace(trace)
    if args.response:
        with Path(args.response).open("w", encoding="utf-8") as handle:
            json.dump(response.__dict__, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    if args.print_message:
        print(response.message)


def build_request_from_note(args: argparse.Namespace) -> dict:
    condition = canonical_condition(args.condition)
    lower, upper = default_target_interval(condition)
    verifier_exposure = env_value(
        "PB_VERIFIER_EXPOSURE",
        fallback="EDOS_VERIFIER_EXPOSURE_CONDITION",
        default="unknown",
    )
    skill_exposure = env_value(
        "PB_SKILL_EXPOSURE",
        fallback="EDOS_SKILL_EXPOSURE_CONDITION",
        default=verifier_exposure,
    )
    skill_loaded = bool_env(
        "PB_SKILL_LOADED",
        False,
        fallback="EDOS_SKILL_LOADED",
    )
    workspace = env_value("PB_WORKSPACE", fallback="EDOS_WORKSPACE", default="")
    workspace_progress = inspect_workspace_progress(workspace)
    workspace_context = inspect_workspace_context(
        workspace,
        docs_path=env_value("PB_DOCS_PATH", fallback="EDOS_DOCS_PATH", default=""),
        note=args.note,
    )
    control_signals = make_control_signals(
        TaskProgress(**workspace_progress),
        args.note,
    )
    cost_proxy = build_cost_proxy(args.turn_id, workspace_progress=workspace_progress)
    note = args.note
    return {
        "run_id": args.run_id,
        "task_id": args.task_id,
        "turn_id": args.turn_id,
        "condition": condition,
        "behavior_surface": args.surface,
        "agent_summary": {
            "behavior_check_note": note,
            "workspace_progress": workspace_progress,
            "workspace_context": workspace_context,
        },
        "cost_state": {
            "estimated_extra_cost": cost_proxy["estimated_extra_cost"],
            "target_extra_cost_lower": lower,
            "target_extra_cost_upper": upper,
            "cost_proxy_source": cost_proxy["cost_proxy_source"],
            "cost_proxy_units_per_verifier_call": cost_proxy[
                "cost_proxy_units_per_verifier_call"
            ],
            "cost_proxy_initial_free_calls": cost_proxy[
                "cost_proxy_initial_free_calls"
            ],
            "cost_proxy_chargeable_calls": cost_proxy[
                "cost_proxy_chargeable_calls"
            ],
            "cost_proxy_response_chars_per_unit": cost_proxy[
                "cost_proxy_response_chars_per_unit"
            ],
            "cost_proxy_projected_response_chars": cost_proxy[
                "cost_proxy_projected_response_chars"
            ],
            "cost_proxy_response_projection_mode": cost_proxy[
                "cost_proxy_response_projection_mode"
            ],
            "cost_proxy_response_projection_floor": cost_proxy[
                "cost_proxy_response_projection_floor"
            ],
            "cost_proxy_response_projection_window": cost_proxy[
                "cost_proxy_response_projection_window"
            ],
            "cost_proxy_chargeable_response_chars": cost_proxy[
                "cost_proxy_chargeable_response_chars"
            ],
            "cost_proxy_observed_response_chars_before_call": cost_proxy[
                "cost_proxy_observed_response_chars_before_call"
            ],
            "cost_proxy_observed_response_calls_before_call": cost_proxy[
                "cost_proxy_observed_response_calls_before_call"
            ],
        },
        "context_state": {},
        "task_progress": workspace_progress,
        "verifier_adoption": {
            "exposure_condition": verifier_exposure,
            "skill_exposure_condition": skill_exposure,
            "skill_loaded": skill_loaded,
            "skill_name": env_value(
                "PB_SKILL_NAME",
                fallback="EDOS_SKILL_NAME",
                default="",
            ),
            "skill_config_hash": env_value(
                "PB_SKILL_CONFIG_HASH",
                fallback="EDOS_SKILL_CONFIG_HASH",
                default="",
            ),
            "verifier_calls_so_far": args.turn_id,
            "first_verifier_call_turn": 1,
        },
        "control_signals": control_signals.__dict__,
    }


def build_cost_proxy(
    turn_id: int,
    *,
    workspace_progress: dict | None = None,
) -> dict:
    units_per_call = nonnegative_float_env(
        "PB_COST_PROXY_UNITS_PER_VERIFIER_CALL",
        1.0,
        fallback="EDOS_COST_PROXY_UNITS_PER_VERIFIER_CALL",
    )
    initial_free_calls = nonnegative_int_env(
        "PB_COST_PROXY_INITIAL_FREE_CALLS",
        1,
        fallback="EDOS_COST_PROXY_INITIAL_FREE_CALLS",
    )
    source = env_value(
        "PB_COST_PROXY_SOURCE",
        fallback="EDOS_COST_PROXY_SOURCE",
        default="verifier_call_count_proxy",
    )
    require_candidate = bool_env(
        "PB_COST_PROXY_REQUIRE_CANDIDATE",
        False,
        fallback="EDOS_COST_PROXY_REQUIRE_CANDIDATE",
    )
    response_chars_per_unit = nonnegative_float_env(
        "PB_COST_PROXY_RESPONSE_CHARS_PER_UNIT",
        0.0,
        fallback="EDOS_COST_PROXY_RESPONSE_CHARS_PER_UNIT",
    )
    projected_response_chars = nonnegative_int_env(
        "PB_COST_PROXY_PROJECTED_RESPONSE_CHARS",
        0,
        fallback="EDOS_COST_PROXY_PROJECTED_RESPONSE_CHARS",
    )
    response_projection_mode = normalized_projection_mode(
        env_value(
            "PB_COST_PROXY_RESPONSE_PROJECTION_MODE",
            fallback="EDOS_COST_PROXY_RESPONSE_PROJECTION_MODE",
            default="fixed",
        )
    )
    response_projection_floor = nonnegative_int_env(
        "PB_COST_PROXY_RESPONSE_PROJECTION_FLOOR",
        0,
        fallback="EDOS_COST_PROXY_RESPONSE_PROJECTION_FLOOR",
    )
    response_projection_window = nonnegative_int_env(
        "PB_COST_PROXY_RESPONSE_PROJECTION_WINDOW",
        0,
        fallback="EDOS_COST_PROXY_RESPONSE_PROJECTION_WINDOW",
    )
    proxy_state = load_cost_proxy_state_path()
    observed_response_chars = nonnegative_int_value(
        proxy_state.get("observed_response_chars", 0)
    )
    observed_response_calls = nonnegative_int_value(
        proxy_state.get("observed_response_calls", 0)
    )
    effective_projected_response_chars = project_response_chars(
        configured_projection=projected_response_chars,
        projection_mode=response_projection_mode,
        projection_floor=response_projection_floor,
        projection_window=response_projection_window,
        state=proxy_state,
    )
    if require_candidate:
        candidate_ready = bool((workspace_progress or {}).get("has_candidate"))
        if candidate_ready:
            first_candidate_turn = remember_first_candidate_turn(int(turn_id))
            post_candidate_calls = max(0, int(turn_id) - first_candidate_turn + 1)
            chargeable_calls = max(0, post_candidate_calls - initial_free_calls)
        else:
            chargeable_calls = 0
    else:
        chargeable_calls = max(0, int(turn_id) - initial_free_calls)
    chargeable_response_chars = recorded_chargeable_response_chars()
    response_char_units = 0.0
    if response_chars_per_unit > 0:
        recorded_calls = recorded_chargeable_response_calls()
        pending_calls = max(0, chargeable_calls - recorded_calls)
        projected_chars = pending_calls * effective_projected_response_chars
        response_char_units = (
            float(chargeable_response_chars + projected_chars)
            / response_chars_per_unit
        )
    return {
        "estimated_extra_cost": float(chargeable_calls) * units_per_call
        + response_char_units,
        "cost_proxy_source": source,
        "cost_proxy_units_per_verifier_call": units_per_call,
        "cost_proxy_initial_free_calls": initial_free_calls,
        "cost_proxy_chargeable_calls": chargeable_calls,
        "cost_proxy_response_chars_per_unit": response_chars_per_unit,
        "cost_proxy_projected_response_chars": effective_projected_response_chars,
        "cost_proxy_response_projection_mode": response_projection_mode,
        "cost_proxy_response_projection_floor": response_projection_floor,
        "cost_proxy_response_projection_window": response_projection_window,
        "cost_proxy_chargeable_response_chars": chargeable_response_chars,
        "cost_proxy_observed_response_chars_before_call": observed_response_chars,
        "cost_proxy_observed_response_calls_before_call": observed_response_calls,
    }


def env_value(name: str, *, fallback: str | None = None, default: str = "") -> str:
    raw = os.environ.get(name)
    if raw is None and fallback:
        raw = os.environ.get(fallback)
    return default if raw is None else raw


def bool_env(name: str, default: bool, *, fallback: str | None = None) -> bool:
    raw = os.environ.get(name)
    if raw is None and fallback:
        raw = os.environ.get(fallback)
    if raw is None:
        return default
    return raw in {"1", "true", "True", "yes", "YES", "on", "ON"}


def remember_first_candidate_turn(turn_id: int) -> int:
    path = cost_proxy_state_path()
    if not path:
        return turn_id
    data = load_cost_proxy_state(path)
    previous = data.get("first_candidate_turn")
    if isinstance(previous, int):
        first_turn = min(previous, turn_id)
    else:
        first_turn = turn_id
    data["first_candidate_turn"] = first_turn
    save_cost_proxy_state(path, data)
    return first_turn


def recorded_chargeable_response_chars() -> int:
    data = load_cost_proxy_state_path()
    return nonnegative_int_value(data.get("chargeable_response_chars", 0))


def recorded_chargeable_response_calls() -> int:
    data = load_cost_proxy_state_path()
    return nonnegative_int_value(data.get("recorded_chargeable_calls", 0))


def update_cost_proxy_response_state(message: str, cost_state: CostState) -> dict:
    observed_chars = len(message)
    empty_update = {
        "cost_proxy_observed_response_chars": observed_chars,
        "cost_proxy_recorded_response_chars_after_call": cost_state.cost_proxy_chargeable_response_chars,
        "cost_proxy_recorded_response_calls_after_call": 0,
        "cost_proxy_recorded_observed_response_chars_after_call": cost_state.cost_proxy_observed_response_chars_before_call,
        "cost_proxy_recorded_observed_response_calls_after_call": cost_state.cost_proxy_observed_response_calls_before_call,
    }
    path = cost_proxy_state_path()
    if not path:
        return empty_update
    data = load_cost_proxy_state(path)
    updated_observed = record_observed_response_chars(
        data,
        observed_chars,
        window=cost_state.cost_proxy_response_projection_window,
    )
    empty_update = {
        **empty_update,
        "cost_proxy_recorded_observed_response_chars_after_call": updated_observed[
            "observed_response_chars"
        ],
        "cost_proxy_recorded_observed_response_calls_after_call": updated_observed[
            "observed_response_calls"
        ],
    }
    if cost_state.cost_proxy_response_chars_per_unit <= 0:
        save_cost_proxy_state(path, data)
        return empty_update
    recorded_calls = nonnegative_int_value(data.get("recorded_chargeable_calls", 0))
    chargeable_calls = max(0, int(cost_state.cost_proxy_chargeable_calls))
    if chargeable_calls <= recorded_calls:
        save_cost_proxy_state(path, data)
        return {
            **empty_update,
            "cost_proxy_recorded_response_calls_after_call": recorded_calls,
        }
    updated_chars = (
        nonnegative_int_value(data.get("chargeable_response_chars", 0))
        + observed_chars
    )
    data["recorded_chargeable_calls"] = chargeable_calls
    data["chargeable_response_chars"] = updated_chars
    save_cost_proxy_state(path, data)
    return {
        "cost_proxy_observed_response_chars": observed_chars,
        "cost_proxy_recorded_response_chars_after_call": updated_chars,
        "cost_proxy_recorded_response_calls_after_call": chargeable_calls,
        "cost_proxy_recorded_observed_response_chars_after_call": updated_observed[
            "observed_response_chars"
        ],
        "cost_proxy_recorded_observed_response_calls_after_call": updated_observed[
            "observed_response_calls"
        ],
    }


def normalized_projection_mode(raw: str) -> str:
    return raw if raw in {"fixed", "rolling_mean"} else "fixed"


def project_response_chars(
    *,
    configured_projection: int,
    projection_mode: str,
    projection_floor: int,
    projection_window: int,
    state: dict,
) -> int:
    fallback = max(configured_projection, projection_floor)
    if projection_mode != "rolling_mean":
        return fallback
    raw_history = state.get("observed_response_char_history", [])
    if not isinstance(raw_history, list):
        raw_history = []
    history = [
        nonnegative_int_value(item)
        for item in raw_history
    ]
    history = [item for item in history if item > 0]
    if projection_window > 0:
        history = history[-projection_window:]
    if not history:
        return fallback
    return max(projection_floor, int(round(sum(history) / len(history))))


def record_observed_response_chars(data: dict, observed_chars: int, *, window: int) -> dict:
    total_chars = nonnegative_int_value(data.get("observed_response_chars", 0))
    total_calls = nonnegative_int_value(data.get("observed_response_calls", 0))
    raw_history = data.get("observed_response_char_history", [])
    if not isinstance(raw_history, list):
        raw_history = []
    history = [
        nonnegative_int_value(item)
        for item in raw_history
    ]
    history.append(max(0, observed_chars))
    max_history = window if window > 0 else 20
    data["observed_response_char_history"] = history[-max_history:]
    data["observed_response_chars"] = total_chars + max(0, observed_chars)
    data["observed_response_calls"] = total_calls + 1
    return {
        "observed_response_chars": data["observed_response_chars"],
        "observed_response_calls": data["observed_response_calls"],
    }


def cost_proxy_state_path() -> Path | None:
    explicit = env_value(
        "PB_COST_PROXY_STATE_PATH",
        fallback="EDOS_COST_PROXY_STATE_PATH",
        default="",
    )
    if explicit:
        return Path(explicit)
    run_dir = env_value("PB_RUN_DIR", fallback="EDOS_RUN_DIR", default="")
    if run_dir:
        return Path(run_dir) / "cost_proxy_state.json"
    return None


def load_cost_proxy_state_path() -> dict:
    path = cost_proxy_state_path()
    if not path:
        return {}
    return load_cost_proxy_state(path)


def load_cost_proxy_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_cost_proxy_state(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def nonnegative_float_env(
    name: str,
    default: float,
    *,
    fallback: str | None = None,
) -> float:
    try:
        value = float(env_value(name, fallback=fallback, default=str(default)))
    except ValueError:
        value = default
    return max(0.0, value)


def nonnegative_int_env(
    name: str,
    default: int,
    *,
    fallback: str | None = None,
) -> int:
    try:
        value = int(env_value(name, fallback=fallback, default=str(default)))
    except ValueError:
        value = default
    return max(0, value)


def nonnegative_int_value(value: object) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        parsed = 0
    return max(0, parsed)


def inspect_workspace_progress(workspace: str | None) -> dict:
    if not workspace:
        return {}
    root = Path(workspace)
    compile_script = root / "compile.sh"
    executable = root / "executable"
    source_markers = [
        "candidate.py",
        "main.py",
        "solution.py",
        "program.py",
        "index.js",
        "main.js",
        "main.c",
        "main.cpp",
        "Cargo.toml",
        "package.json",
    ]
    has_source = any((root / marker).exists() for marker in source_markers)
    return {
        "has_candidate": bool(has_source or executable.exists()),
        "has_build_script": compile_script.exists(),
        "last_compile_success": executable.exists(),
        "last_candidate_run_seen": executable.exists(),
        "final_submission_seen": False,
    }


def inspect_workspace_context(
    workspace: str | None,
    *,
    docs_path: str | None = None,
    note: str = "",
) -> dict:
    context = {
        "probe_note": compact_text(note, 240),
        "docs_file": "",
        "docs_excerpt": "",
        "candidate_file": "",
        "candidate_excerpt": "",
        "candidate_files": [],
        "build_summary": "",
        "recent_error_summary": extract_error_summary(note),
    }
    if not workspace:
        return context
    root = Path(workspace)
    docs_file = choose_docs_file(root, docs_path)
    if docs_file:
        context["docs_file"] = str(docs_file.name)
        context["docs_excerpt"] = read_excerpt(docs_file, 420)
    candidate_files = find_candidate_files(root)
    context["candidate_files"] = [path.name for path in candidate_files[:5]]
    if candidate_files:
        context["candidate_file"] = candidate_files[0].name
        context["candidate_excerpt"] = read_excerpt(candidate_files[0], 420)
    compile_script = root / "compile.sh"
    executable = root / "executable"
    build_parts = []
    if compile_script.exists():
        build_parts.append("compile.sh present")
    if executable.exists():
        build_parts.append("executable present")
    if compile_script.exists():
        excerpt = read_excerpt(compile_script, 180)
        if excerpt:
            build_parts.append(f"compile.sh: {excerpt}")
    context["build_summary"] = compact_text("; ".join(build_parts), 260)
    return context


def choose_docs_file(root: Path, docs_path: str | None) -> Path | None:
    candidates: list[Path] = []
    if docs_path:
        path = Path(docs_path)
        if path.exists():
            if path.is_file():
                candidates.append(path)
            elif path.is_dir():
                candidates.extend(sorted(path.glob("*.md")))
                candidates.extend(sorted(path.glob("*.txt")))
    candidates.extend(
        path
        for path in [
            root / "TASK_DOCS.md",
            root / "README.md",
            root / "README.txt",
        ]
        if path.exists()
    )
    return candidates[0] if candidates else None


def find_candidate_files(root: Path) -> list[Path]:
    names = [
        "candidate.py",
        "main.py",
        "solution.py",
        "program.py",
        "index.js",
        "main.js",
        "main.c",
        "main.cpp",
        "Cargo.toml",
        "package.json",
    ]
    return [root / name for name in names if (root / name).is_file()]


def read_excerpt(path: Path, max_chars: int) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return compact_text(text, max_chars)


def compact_text(text: str, max_chars: int) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max(0, max_chars - 3)].rstrip() + "..."


def extract_error_summary(text: str) -> str:
    lowered_markers = ("error", "failed", "failure", "traceback", "stderr", "exit")
    lines = [
        line.strip()
        for line in str(text or "").splitlines()
        if any(marker in line.lower() for marker in lowered_markers)
    ]
    return compact_text(" | ".join(lines), 260)


def maybe_append_controller_trace(trace: dict) -> None:
    run_dir = env_value("PB_RUN_DIR", fallback="EDOS_RUN_DIR", default="")
    if not run_dir:
        return
    path = Path(run_dir).resolve() / "controller_trace.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"timestamp": trace_timestamp(), **trace}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False))
        handle.write("\n")


def trace_timestamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def infer_mode(condition: str) -> str:
    return infer_verifier_mode(condition)


def default_target_interval(condition: str) -> tuple[float, float]:
    condition = canonical_condition(condition)
    if "high" in condition:
        return 8.0, 12.0
    if "low" in condition:
        return 1.5, 2.5
    if is_clean_condition(condition) or condition == "no_attack":
        return 0.0, 0.0
    return 4.0, 6.0


if __name__ == "__main__":
    main()
