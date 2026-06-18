from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from edos.analysis.csvio import read_csv_dicts
from edos.analysis.aggregate import aggregate, iter_jsonl, write_csv


METHODOLOGY_REQUIREMENTS = [
    {
        "claim_id": "A1",
        "claim_type": "assumption",
        "claim": "history accumulation is observable through trajectory, events, and usage growth",
        "required_fields": ["events.jsonl", "usage.json", "trajectory.jsonl"],
        "evidence_role": "history-augmented task process",
    },
    {
        "claim_id": "A2",
        "claim_type": "assumption",
        "claim": "resource cost is measured or proxied through token, call, and wall-clock fields",
        "required_fields": ["input_tokens_est", "output_tokens_est", "api_calls", "usage_source"],
        "evidence_role": "cost monotonicity proxy",
    },
    {
        "claim_id": "A3/P0",
        "claim_type": "assumption/proposition",
        "claim": "adoption or trigger surface is separated from verifier feedback policy",
        "required_fields": [
            "verifier_exposure_condition",
            "entry_surface",
            "verifier_calls",
            "first_verifier_call_turn",
        ],
        "evidence_role": "adoption surface gate",
    },
    {
        "claim_id": "A4/P2",
        "claim_type": "assumption/proposition",
        "claim": "verifier feedback stays tied to ProgramBench behavior surfaces",
        "required_fields": [
            "behavior_surface",
            "task_local_anchor_count",
            "validation_graph_surface_count",
        ],
        "evidence_role": "semantic relevance",
    },
    {
        "claim_id": "A5/P4",
        "claim_type": "assumption/proposition",
        "claim": "task utility remains observable while semantic echo is used as a relevance constraint",
        "required_fields": [
            "candidate_build_success",
            "final_submission_seen",
            "tests_passed_fraction",
            "failure_label",
            "task_local_anchor_count",
        ],
        "evidence_role": "utility preservation",
    },
    {
        "claim_id": "A6/P5",
        "claim_type": "assumption/proposition",
        "claim": "controller uses observable cost, context, utility, repair, and batching proxies",
        "required_fields": [
            "controller_estimated_extra_cost",
            "target_extra_cost_lower",
            "target_extra_cost_upper",
            "utility_risk",
            "repair_needed",
            "batching_signal",
        ],
        "evidence_role": "adaptive budget control",
    },
    {
        "claim_id": "D4/P1",
        "claim_type": "definition/proposition",
        "claim": "polluted verifier constructs an adversarial validation graph",
        "required_fields": [
            "validation_graph_node_count",
            "validation_graph_branch_count",
            "validation_graph_max_depth",
            "validation_graph_surface_histogram",
        ],
        "evidence_role": "validation obligation graph",
    },
    {
        "claim_id": "P3",
        "claim_type": "proposition",
        "claim": "latch and dynamic markers produce non-compressible node dependency evidence",
        "required_fields": ["stage_marker", "marker_echoed", "latch_state", "derivation_step"],
        "evidence_role": "non-compressible dependency",
    },
    {
        "claim_id": "P5/RQ2",
        "claim_type": "proposition/experiment",
        "claim": "controller proxy target hits are recorded separately from reported-token target hits",
        "required_fields": [
            "controller_target_interval_hit",
            "controller_target_cost_error",
            "target_interval_hit",
            "target_cost_error",
        ],
        "evidence_role": "budget controllability boundary",
    },
]


MECHANISM_TO_CLAIM = {
    "no_latch": "P3",
    "no_dynamic_marker": "P3",
    "no_echo": "A5/P4",
    "no_budget_control": "A6/P5",
    "no_pagination": "A6/P5",
    "no_paginated_report": "A6/P5",
    "no_repair": "P3/P5",
    "no_graph": "D4/P1",
    "no_shrink": "A5/P5",
    "no_utility_guard": "A5/P4",
    "static_behavior_surface": "A4/P2",
    "naive_padding": "A4/P2",
    "fixed_depth_tree": "A6/P5",
    "fixed_shallow": "A6/P5",
    "fixed_deep": "A6/P5",
    "conservative_adaptation": "A6/P5",
}


def build_methodology_evidence_bundle(
    run_dir: str | Path,
    *,
    output_dir: str | Path | None = None,
    refresh_aggregate: bool = False,
) -> dict[str, Path]:
    root = Path(run_dir)
    aggregate_dir = root / "aggregate"
    if refresh_aggregate or not (aggregate_dir / "runs.csv").exists():
        aggregate(root)

    bundle_dir = Path(output_dir) if output_dir else aggregate_dir / "methodology_evidence"
    bundle_dir.mkdir(parents=True, exist_ok=True)

    tables = MethodologyTables.load(aggregate_dir)
    trace_rows = build_trace_field_rows(root, tables.runs)
    claim_rows = build_methodology_claim_rows(tables, trace_rows)
    mechanism_rows = build_mechanism_link_rows(tables.ablation)
    summary = build_methodology_summary(
        run_dir=root,
        claim_rows=claim_rows,
        trace_rows=trace_rows,
        mechanism_rows=mechanism_rows,
    )

    paths = {
        "claims": bundle_dir / "methodology_claims.csv",
        "trace_fields": bundle_dir / "methodology_trace_fields.csv",
        "mechanisms": bundle_dir / "methodology_mechanism_links.csv",
        "summary": bundle_dir / "methodology_evidence_summary.json",
        "boundaries": bundle_dir / "methodology_boundaries.md",
    }
    write_csv(paths["claims"], claim_rows)
    write_csv(paths["trace_fields"], trace_rows)
    write_csv(paths["mechanisms"], mechanism_rows)
    paths["summary"].write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    paths["boundaries"].write_text(
        render_methodology_boundaries(summary),
        encoding="utf-8",
    )
    return paths


class MethodologyTables:
    def __init__(
        self,
        *,
        runs: list[dict[str, str]],
        repeat: list[dict[str, str]],
        ablation: list[dict[str, str]],
        target: list[dict[str, str]],
    ):
        self.runs = runs
        self.repeat = repeat
        self.ablation = ablation
        self.target = target

    @classmethod
    def load(cls, aggregate_dir: Path) -> "MethodologyTables":
        return cls(
            runs=read_optional_csv(aggregate_dir / "runs.csv"),
            repeat=read_optional_csv(aggregate_dir / "repeat_summary.csv"),
            ablation=read_optional_csv(aggregate_dir / "ablation.csv"),
            target=read_optional_csv(aggregate_dir / "target_cost_error.csv"),
        )


def build_methodology_claim_rows(
    tables: MethodologyTables,
    trace_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    field_index = build_field_index(tables, trace_rows)
    rows: list[dict[str, object]] = []
    for spec in METHODOLOGY_REQUIREMENTS:
        required = list(spec["required_fields"])
        statuses = [field_index.get(field, "missing") for field in required]
        covered = sum(status != "missing" for status in statuses)
        observed = sum(status == "observed" for status in statuses)
        rows.append(
            {
                "claim_id": spec["claim_id"],
                "claim_type": spec["claim_type"],
                "claim": spec["claim"],
                "evidence_role": spec["evidence_role"],
                "required_fields": ";".join(required),
                "covered_fields": covered,
                "observed_fields": observed,
                "missing_fields": ";".join(
                    field
                    for field, status in zip(required, statuses)
                    if status == "missing"
                ),
                "coverage_status": claim_coverage_status(
                    required_count=len(required),
                    covered=covered,
                    observed=observed,
                ),
                "paper_use_scope": claim_scope(spec["claim_id"], tables),
            }
        )
    return rows


def build_trace_field_rows(
    run_dir: Path,
    runs: list[dict[str, str]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in runs:
        run_root = locate_run_dir(run_dir, row)
        events = iter_jsonl(run_root / "events.jsonl") if run_root else []
        controller = iter_jsonl(run_root / "controller_trace.jsonl") if run_root else []
        trajectory_exists = bool(run_root and (run_root / "trajectory.jsonl").exists())
        usage_exists = bool(run_root and (run_root / "usage.json").exists())
        rows.append(
            {
                "run_id": row.get("run_id", ""),
                "condition": row.get("condition", ""),
                "agent_runtime": row.get("agent_runtime", ""),
                "task_id": row.get("task_id", ""),
                "events_jsonl_present": bool(events),
                "usage_json_present": usage_exists,
                "trajectory_jsonl_present": trajectory_exists,
                "controller_trace_present": bool(controller),
                "verifier_event_count": sum(
                    1 for event in events if event.get("event_type") == "verifier_call"
                ),
                "controller_trace_rows": len(controller),
                "theory_source_values": join_sorted(
                    row.get("theory_source")
                    for row in controller
                    if value_present(row.get("theory_source"))
                ),
                "derivation_step_values": join_sorted(
                    row.get("derivation_step")
                    for row in controller
                    if value_present(row.get("derivation_step"))
                ),
                "controller_state_values": join_sorted(
                    row.get("next_state") or row.get("controller_state")
                    for row in controller
                    if value_present(row.get("next_state") or row.get("controller_state"))
                ),
                "behavior_surface_values": join_sorted(
                    row.get("behavior_surface")
                    for row in controller
                    if value_present(row.get("behavior_surface"))
                ),
                "stage_marker_seen": any(value_present(row.get("stage_marker")) for row in controller),
                "marker_echoed_seen": any(truthy(row.get("marker_echoed")) for row in controller),
                "latch_state_values": join_sorted(
                    row.get("latch_state")
                    for row in controller
                    if value_present(row.get("latch_state"))
                ),
            }
        )
    return rows


def build_mechanism_link_rows(
    ablation_rows: list[dict[str, str]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in ablation_rows:
        condition = row.get("condition", "")
        rows.append(
            {
                "condition": condition,
                "target_level": row.get("target_level", ""),
                "linked_claim_id": MECHANISM_TO_CLAIM.get(condition, ""),
                "removed_mechanism": row.get("removed_mechanism", ""),
                "evidence_question": row.get("evidence_question", ""),
                "adaptive_baseline_condition": row.get(
                    "adaptive_baseline_condition",
                    "",
                ),
                "delta_controller_hit_rate_vs_adaptive": row.get(
                    "delta_controller_hit_rate_vs_adaptive",
                    "",
                ),
                "delta_validation_graph_node_count_vs_adaptive": row.get(
                    "delta_validation_graph_node_count_vs_adaptive",
                    "",
                ),
                "delta_verifier_calls_vs_adaptive": row.get(
                    "delta_verifier_calls_vs_adaptive",
                    "",
                ),
                "candidate_build_success_rate": row.get(
                    "candidate_build_success_rate",
                    "",
                ),
                "final_submission_rate": row.get("final_submission_rate", ""),
                "mechanism_signal": mechanism_signal(row),
                "paper_use_scope": "mechanism_evidence_not_paper_main_by_itself",
            }
        )
    return rows


def build_field_index(
    tables: MethodologyTables,
    trace_rows: list[dict[str, object]],
) -> dict[str, str]:
    index: dict[str, str] = {}
    for field in [
        "input_tokens_est",
        "output_tokens_est",
        "api_calls",
        "usage_source",
        "verifier_exposure_condition",
        "entry_surface",
        "verifier_calls",
        "first_verifier_call_turn",
        "task_local_anchor_count",
        "validation_graph_surface_count",
        "candidate_build_success",
        "final_submission_seen",
        "tests_passed_fraction",
        "failure_label",
        "controller_estimated_extra_cost",
        "target_extra_cost_lower",
        "target_extra_cost_upper",
        "utility_risk",
        "repair_needed",
        "batching_signal",
        "validation_graph_node_count",
        "validation_graph_branch_count",
        "validation_graph_max_depth",
        "validation_graph_surface_histogram",
    ]:
        index[field] = field_status(tables.runs, field)
    for field in [
        "controller_target_interval_hit",
        "controller_target_cost_error",
        "target_interval_hit",
        "target_cost_error",
    ]:
        index[field] = field_status(tables.target, field)

    index["events.jsonl"] = "observed" if any(truthy(row.get("events_jsonl_present")) for row in trace_rows) else "missing"
    index["usage.json"] = "observed" if any(truthy(row.get("usage_json_present")) for row in trace_rows) else "missing"
    index["trajectory.jsonl"] = "observed" if any(truthy(row.get("trajectory_jsonl_present")) for row in trace_rows) else "missing"
    index["behavior_surface"] = trace_observed(trace_rows, "behavior_surface_values")
    index["stage_marker"] = "observed" if any(truthy(row.get("stage_marker_seen")) for row in trace_rows) else "missing"
    index["marker_echoed"] = "observed" if any(truthy(row.get("marker_echoed_seen")) for row in trace_rows) else "covered_empty"
    index["latch_state"] = trace_observed(trace_rows, "latch_state_values")
    index["derivation_step"] = trace_observed(trace_rows, "derivation_step_values")
    return index


def build_methodology_summary(
    *,
    run_dir: Path,
    claim_rows: list[dict[str, object]],
    trace_rows: list[dict[str, object]],
    mechanism_rows: list[dict[str, object]],
) -> dict[str, Any]:
    return {
        "run_dir": str(run_dir),
        "claim_rows": len(claim_rows),
        "covered_claims": sum(
            1 for row in claim_rows if row.get("coverage_status") == "covered_observed"
        ),
        "partial_claims": sum(
            1 for row in claim_rows if row.get("coverage_status") == "partially_covered"
        ),
        "missing_claims": sum(
            1 for row in claim_rows if row.get("coverage_status") == "missing"
        ),
        "trace_runs": len(trace_rows),
        "runs_with_controller_trace": sum(
            1 for row in trace_rows if truthy(row.get("controller_trace_present"))
        ),
        "mechanism_link_rows": len(mechanism_rows),
        "linked_claims": sorted(
            {
                str(row.get("linked_claim_id", ""))
                for row in mechanism_rows
                if row.get("linked_claim_id")
            }
        ),
        "claim_boundary": (
            "Methodology coverage shows whether logs expose the paper-method fields; "
            "it does not prove the empirical effect without admitted experiment results."
        ),
    }


def render_methodology_boundaries(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Methodology Evidence Boundaries",
            "",
            "This bundle maps formal-method claims to logged fields and mechanism tables.",
            "",
            f"- covered claims: {summary['covered_claims']}/{summary['claim_rows']}",
            f"- runs with controller trace: {summary['runs_with_controller_trace']}/{summary['trace_runs']}",
            f"- mechanism link rows: {summary['mechanism_link_rows']}",
            "",
            "## Interpretation",
            "",
            "- Field coverage is necessary for the L3 methodology claim, but it is not sufficient by itself.",
            "- Mechanism ablations should be reported as mechanism evidence unless paper-main admission gates pass.",
            "- Controller proxy target hits and reported-token target hits remain separate evidence.",
            "",
        ]
    )


def locate_run_dir(run_dir: Path, row: dict[str, str]) -> Path | None:
    if value_present(row.get("run_dir")):
        path = Path(str(row["run_dir"]))
        if path.exists():
            return path
    if value_present(row.get("run_id")):
        path = run_dir / str(row["run_id"])
        if path.exists():
            return path
    return None


def claim_coverage_status(
    *,
    required_count: int,
    covered: int,
    observed: int,
) -> str:
    if covered == 0:
        return "missing"
    if covered < required_count:
        return "partially_covered"
    if observed == required_count:
        return "covered_observed"
    return "covered_schema_only"


def claim_scope(claim_id: str, tables: MethodologyTables) -> str:
    if claim_id.startswith("P5") or claim_id.startswith("A6"):
        if tables.target:
            return "controller_proxy_and_reported_token_fields_available"
        return "controller_proxy_only_until_target_table_exists"
    if claim_id.startswith("P3") and not tables.ablation:
        return "trace_field_coverage_without_ablation"
    if tables.ablation:
        return "methodology_and_mechanism_evidence"
    return "methodology_field_coverage_only"


def field_status(rows: list[dict[str, str]], field: str) -> str:
    if not rows:
        return "missing"
    if not any(field in row for row in rows):
        return "missing"
    if any(value_present(row.get(field)) for row in rows):
        return "observed"
    return "covered_empty"


def trace_observed(rows: list[dict[str, object]], field: str) -> str:
    if any(value_present(row.get(field)) for row in rows):
        return "observed"
    return "missing"


def mechanism_signal(row: dict[str, str]) -> str:
    condition = row.get("condition", "")
    if not row.get("adaptive_baseline_condition"):
        return "missing_adaptive_baseline"
    if condition == "no_budget_control":
        return "budget_control_ablation_row"
    if condition in {"no_latch", "no_dynamic_marker"}:
        return "non_compressible_dependency_ablation_row"
    if condition == "no_echo":
        return "semantic_echo_ablation_row"
    if condition in {"no_pagination", "no_paginated_report"}:
        return "pagination_ablation_row"
    if condition == "no_repair":
        return "repair_ablation_row"
    if condition == "no_graph":
        return "validation_graph_ablation_row"
    if condition == "no_shrink":
        return "shrink_guard_ablation_row"
    if condition == "no_utility_guard":
        return "utility_guard_ablation_row"
    if condition == "static_behavior_surface":
        return "behavior_surface_selection_ablation_row"
    if condition == "naive_padding":
        return "task_semantic_validation_ablation_row"
    if condition in {"fixed_depth_tree", "fixed_shallow", "fixed_deep"}:
        return "adaptive_policy_ablation_row"
    if condition == "conservative_adaptation":
        return "conservative_controller_variant_row"
    return "mechanism_ablation_row"


def read_optional_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    return read_csv_dicts(path)


def join_sorted(values: Any) -> str:
    out = sorted({str(value) for value in values if value_present(value)})
    return ";".join(out)


def value_present(value: object) -> bool:
    if value is None:
        return False
    return str(value).strip() not in {"", "None", "none", "null"}


def truthy(value: object) -> bool:
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)
