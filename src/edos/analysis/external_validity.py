from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from edos.analysis.csvio import read_csv_dicts
from edos.analysis.aggregate import aggregate, write_csv
from edos.conditions import CLEAN_CONDITIONS
from edos.surfaces import ENTRY_SURFACES, EXPOSURE_TO_ENTRY_SURFACE


AGENT_ROLE = {
    "opencode": "primary_mechanism_runtime",
    "mini_sweagent_programbench": "programbench_aligned_mechanism_validation",
    "openhands": "external_validity_pilot",
}


def build_external_validity_bundle(
    run_dirs: list[str | Path],
    *,
    output_dir: str | Path,
    refresh_aggregate: bool = False,
) -> dict[str, Path]:
    roots = [Path(path) for path in run_dirs]
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    tables = load_external_tables(roots, refresh_aggregate=refresh_aggregate)
    surface_rows = build_agent_surface_rows(tables.runs)
    condition_rows = build_agent_condition_rows(tables.runs, tables.metrics, tables.target)
    summary = build_external_summary(
        run_dirs=roots,
        runs=tables.runs,
        surface_rows=surface_rows,
        condition_rows=condition_rows,
    )

    paths = {
        "surface": output / "agent_surface_evidence.csv",
        "condition": output / "agent_condition_evidence.csv",
        "summary": output / "external_validity_summary.json",
        "boundaries": output / "external_validity_boundaries.md",
    }
    write_csv(paths["surface"], surface_rows)
    write_csv(paths["condition"], condition_rows)
    paths["summary"].write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    paths["boundaries"].write_text(render_external_boundaries(summary), encoding="utf-8")
    return paths


class ExternalTables:
    def __init__(
        self,
        *,
        runs: list[dict[str, str]],
        metrics: list[dict[str, str]],
        target: list[dict[str, str]],
    ):
        self.runs = runs
        self.metrics = metrics
        self.target = target


def load_external_tables(
    run_dirs: list[Path],
    *,
    refresh_aggregate: bool,
) -> ExternalTables:
    runs: list[dict[str, str]] = []
    metrics: list[dict[str, str]] = []
    target: list[dict[str, str]] = []
    for root in run_dirs:
        aggregate_dir = root / "aggregate"
        if refresh_aggregate or not (aggregate_dir / "runs.csv").exists():
            aggregate(root)
        source_label = str(root)
        runs.extend(add_source_dir(read_optional_csv(aggregate_dir / "runs.csv"), source_label))
        metrics.extend(
            add_source_dir(read_optional_csv(aggregate_dir / "metrics.csv"), source_label)
        )
        target.extend(
            add_source_dir(
                read_optional_csv(aggregate_dir / "target_cost_error.csv"),
                source_label,
            )
        )
    return ExternalTables(runs=runs, metrics=metrics, target=target)


def add_source_dir(rows: list[dict[str, str]], source_dir: str) -> list[dict[str, str]]:
    out = []
    for row in rows:
        current = dict(row)
        current["source_run_dir"] = source_dir
        out.append(current)
    return out


def build_agent_surface_rows(runs: list[dict[str, str]]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str, str, str], list[dict[str, str]]] = {}
    for row in runs:
        key = surface_key(row)
        groups.setdefault(key, []).append(row)

    out: list[dict[str, object]] = []
    for key, rows in sorted(groups.items()):
        adopted = [row for row in rows if positive_int(row.get("verifier_calls")) > 0]
        complete = [row for row in rows if truthy(row.get("run_record_complete"))]
        no_leak = [
            row for row in rows if not truthy(row.get("agent_facing_condition_leak"))
        ]
        official = [
            row
            for row in rows
            if row.get("programbench_scoring_mode") == "official_tests_json"
        ]
        out.append(
            {
                "agent_runtime": key[0],
                "agent_role": agent_role(key[0]),
                "model": key[1],
                "verifier_exposure_condition": key[2],
                "entry_surface": key[3],
                "run_dirs": join_sorted({row.get("source_run_dir", "") for row in rows}),
                "experiments": join_sorted({row.get("experiment_name", "") for row in rows}),
                "tasks": len({row.get("task_id", "") for row in rows if row.get("task_id")}),
                "conditions": len(
                    {row.get("condition", "") for row in rows if row.get("condition")}
                ),
                "runs": len(rows),
                "complete_runs": len(complete),
                "complete_rate": ratio(len(complete), len(rows)),
                "adopted_runs": len(adopted),
                "verifier_adoption_rate": ratio(len(adopted), len(rows)),
                "runs_with_no_verifier_call": len(rows) - len(adopted),
                "avg_verifier_calls_per_run": mean(
                    [positive_int(row.get("verifier_calls")) for row in rows]
                ),
                "avg_blocked_verifier_attempts_per_run": mean(
                    [positive_int(row.get("verifier_blocked_attempts")) for row in rows]
                ),
                "candidate_build_success_rate": bool_rate(
                    rows, "candidate_build_success"
                ),
                "final_submission_rate": bool_rate(rows, "final_submission_seen"),
                "failure_rate": ratio(
                    sum(1 for row in rows if value_present(row.get("failure_label"))),
                    len(rows),
                ),
                "no_agent_facing_leak_rate": ratio(len(no_leak), len(rows)),
                "official_tests_json_runs": len(official),
                "usage_sources": join_sorted({row.get("usage_source", "") for row in rows}),
                "external_validity_scope": surface_scope(key[0], rows),
            }
        )
    return out


def build_agent_condition_rows(
    runs: list[dict[str, str]],
    metrics: list[dict[str, str]],
    target_rows: list[dict[str, str]],
) -> list[dict[str, object]]:
    metric_by_key = {
        metric_key(row): row
        for row in metrics
        if row.get("run_id")
    }
    target_by_key = {
        metric_key(row): row
        for row in target_rows
        if row.get("run_id")
    }
    groups: dict[tuple[str, str, str, str, str, str], list[dict[str, str]]] = {}
    for row in runs:
        key = condition_key(row)
        groups.setdefault(key, []).append(row)

    out: list[dict[str, object]] = []
    for key, rows in sorted(groups.items()):
        metric_rows = [
            metric_by_key[metric_key(row)]
            for row in rows
            if metric_key(row) in metric_by_key
        ]
        matching_targets = [
            target_by_key[metric_key(row)]
            for row in rows
            if metric_key(row) in target_by_key
        ]
        official = [
            row
            for row in rows
            if row.get("programbench_scoring_mode") == "official_tests_json"
        ]
        out.append(
            {
                "agent_runtime": key[0],
                "agent_role": agent_role(key[0]),
                "model": key[1],
                "verifier_exposure_condition": key[2],
                "entry_surface": key[3],
                "condition": key[4],
                "target_level": key[5],
                "run_dirs": join_sorted({row.get("source_run_dir", "") for row in rows}),
                "tasks": len({row.get("task_id", "") for row in rows if row.get("task_id")}),
                "runs": len(rows),
                "complete_rate": ratio(
                    sum(1 for row in rows if truthy(row.get("run_record_complete"))),
                    len(rows),
                ),
                "verifier_adoption_rate": ratio(
                    sum(1 for row in rows if positive_int(row.get("verifier_calls")) > 0),
                    len(rows),
                ),
                "avg_verifier_calls": mean(
                    [positive_int(row.get("verifier_calls")) for row in rows]
                ),
                "avg_total_tokens_est": mean(
                    [total_tokens_from_row(row) for row in rows]
                ),
                "avg_extra_tokens_est": mean_present(
                    [row.get("extra_tokens_est", "") for row in metric_rows]
                ),
                "positive_amplification_rate": positive_rate(
                    [row.get("extra_tokens_est", "") for row in metric_rows]
                ),
                "controller_target_interval_hit_rate": bool_rate(
                    matching_targets, "controller_target_interval_hit"
                ),
                "reported_token_target_interval_hit_rate": bool_rate(
                    [
                        row
                        for row in matching_targets
                        if truthy(row.get("baseline_available"))
                    ],
                    "target_interval_hit",
                ),
                "candidate_build_success_rate": bool_rate(
                    rows, "candidate_build_success"
                ),
                "final_submission_rate": bool_rate(rows, "final_submission_seen"),
                "failure_rate": ratio(
                    sum(1 for row in rows if value_present(row.get("failure_label"))),
                    len(rows),
                ),
                "no_agent_facing_leak_rate": ratio(
                    sum(
                        1
                        for row in rows
                        if not truthy(row.get("agent_facing_condition_leak"))
                    ),
                    len(rows),
                ),
                "official_tests_json_runs": len(official),
                "condition_claim_scope": condition_scope(key[0], key[4], rows),
            }
        )
    return out


def build_external_summary(
    *,
    run_dirs: list[Path],
    runs: list[dict[str, str]],
    surface_rows: list[dict[str, object]],
    condition_rows: list[dict[str, object]],
) -> dict[str, Any]:
    agents = sorted({row.get("agent_runtime", "") for row in runs if row.get("agent_runtime")})
    surfaces = sorted({normalized_surface(row) for row in runs if normalized_surface(row)})
    official_runs = sum(
        1 for row in runs if row.get("programbench_scoring_mode") == "official_tests_json"
    )
    return {
        "run_dirs": [str(path) for path in run_dirs],
        "runs": len(runs),
        "agent_runtimes": agents,
        "agent_runtime_count": len(agents),
        "entry_surfaces": surfaces,
        "entry_surface_count": len(surfaces),
        "tasks": len({row.get("task_id", "") for row in runs if row.get("task_id")}),
        "surface_rows": len(surface_rows),
        "condition_rows": len(condition_rows),
        "official_tests_json_runs": official_runs,
        "complete_runs": sum(1 for row in runs if truthy(row.get("run_record_complete"))),
        "adopted_runs": sum(
            1 for row in runs if positive_int(row.get("verifier_calls")) > 0
        ),
        "no_agent_facing_leak_runs": sum(
            1 for row in runs if not truthy(row.get("agent_facing_condition_leak"))
        ),
        "claim_boundary": (
            "cross-agent evidence describes interface external validity; "
            "paired effects must still be interpreted within each agent/model/surface tuple"
        ),
    }


def render_external_boundaries(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# External Validity Evidence Boundaries",
            "",
            "This bundle merges aggregate outputs across agent runtimes. It does not run new experiments.",
            "",
            f"- agent runtimes: {', '.join(summary['agent_runtimes']) or 'none'}",
            f"- entry surfaces: {', '.join(summary['entry_surfaces']) or 'none'}",
            f"- runs: {summary['runs']}",
            f"- official tests-json runs: {summary['official_tests_json_runs']}",
            "",
            "## Writing Boundary",
            "",
            f"- {summary['claim_boundary']}",
            "- Do not compare absolute token cost across different agent runtimes as a causal attack effect.",
            "- Workflow-enforced or runtime-hooked evidence is a mechanism or upper-bound result, not natural adoption by itself.",
            "",
        ]
    )


def surface_key(row: dict[str, str]) -> tuple[str, str, str, str]:
    exposure = row.get("verifier_exposure_condition", "")
    return (
        row.get("agent_runtime", ""),
        row.get("model", ""),
        exposure,
        normalized_surface(row),
    )


def condition_key(row: dict[str, str]) -> tuple[str, str, str, str, str, str]:
    exposure = row.get("verifier_exposure_condition", "")
    return (
        row.get("agent_runtime", ""),
        row.get("model", ""),
        exposure,
        normalized_surface(row),
        row.get("condition", ""),
        row.get("target_level", ""),
    )


def normalized_surface(row: dict[str, str]) -> str:
    explicit = str(row.get("entry_surface", "") or "").strip()
    exposure = str(row.get("verifier_exposure_condition", "") or "").strip()
    if explicit in ENTRY_SURFACES:
        return explicit
    if explicit in EXPOSURE_TO_ENTRY_SURFACE:
        return EXPOSURE_TO_ENTRY_SURFACE[explicit]
    if exposure in EXPOSURE_TO_ENTRY_SURFACE:
        return EXPOSURE_TO_ENTRY_SURFACE[exposure]
    return explicit or exposure or "unknown"


def metric_key(row: dict[str, str]) -> tuple[str, str]:
    return (row.get("source_run_dir", ""), row.get("run_id", ""))


def agent_role(agent_runtime: str) -> str:
    return AGENT_ROLE.get(agent_runtime, "additional_agent_runtime")


def surface_scope(agent_runtime: str, rows: list[dict[str, str]]) -> str:
    surface = normalized_surface(rows[0]) if rows else ""
    if agent_runtime == "opencode":
        return "primary mechanism and paper-main candidate runtime"
    if agent_runtime == "mini_sweagent_programbench":
        if surface in {"runtime_hook", "workflow_instruction"}:
            return "ProgramBench-aligned mechanism validation or upper-bound evidence"
        return "ProgramBench-aligned adoption probe"
    if agent_runtime == "openhands":
        return "external-validity smoke or pilot evidence"
    return "external-validity evidence for additional runtime"


def condition_scope(
    agent_runtime: str,
    condition: str,
    rows: list[dict[str, str]],
) -> str:
    official = any(row.get("programbench_scoring_mode") == "official_tests_json" for row in rows)
    clean = condition in CLEAN_CONDITIONS or condition == "no_attack"
    if agent_runtime == "opencode" and official:
        return "eligible_for_paper_main_gate_if_admission_passes"
    if clean:
        return "baseline_or_adoption_reference"
    if agent_runtime == "mini_sweagent_programbench":
        return "mechanism_validation_or_upper_bound_not_natural_adoption"
    if agent_runtime == "openhands":
        return "external_validity_pilot_not_paper_main"
    return "external_validity_supporting_evidence"


def read_optional_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    return read_csv_dicts(path)


def join_sorted(values: set[str]) -> str:
    return ";".join(sorted(value for value in values if value))


def positive_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def to_float(value: object) -> float | None:
    try:
        if value in {None, ""}:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def total_tokens_from_row(row: dict[str, str]) -> float:
    return float(positive_int(row.get("input_tokens_est"))) + float(
        positive_int(row.get("output_tokens_est"))
    )


def mean(values: list[float | int]) -> float | str:
    filtered = [float(value) for value in values]
    return sum(filtered) / len(filtered) if filtered else ""


def mean_present(values: list[object]) -> float | str:
    parsed = [value for value in (to_float(item) for item in values) if value is not None]
    return mean(parsed)


def positive_rate(values: list[object]) -> float | str:
    parsed = [value for value in (to_float(item) for item in values) if value is not None]
    return ratio(sum(1 for value in parsed if value > 0), len(parsed))


def bool_rate(rows: list[dict[str, str]], field: str) -> float | str:
    observed = [row for row in rows if value_present(row.get(field))]
    return ratio(sum(1 for row in observed if truthy(row.get(field))), len(observed))


def ratio(numerator: int | float, denominator: int) -> float | str:
    return numerator / denominator if denominator else ""


def truthy(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def value_present(value: object) -> bool:
    return value not in {None, "", "None", "null"}
