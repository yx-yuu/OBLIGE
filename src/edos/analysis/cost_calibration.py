from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from edos.analysis.csvio import read_csv_dicts
from edos.analysis.aggregate import aggregate, write_csv


def build_cost_calibration_bundle(
    run_dir: str | Path,
    *,
    output_dir: str | Path | None = None,
    refresh_aggregate: bool = False,
) -> dict[str, Path]:
    root = Path(run_dir)
    aggregate_dir = root / "aggregate"
    if refresh_aggregate or not (aggregate_dir / "runs.csv").exists():
        aggregate(root)

    bundle_dir = Path(output_dir) if output_dir else aggregate_dir / "cost_calibration"
    bundle_dir.mkdir(parents=True, exist_ok=True)

    tables = CostCalibrationTables.load(aggregate_dir)
    pair_rows = build_cost_calibration_pair_rows(tables)
    summary_rows = build_cost_calibration_summary_rows(pair_rows)
    summary = build_cost_calibration_summary(
        run_dir=root,
        tables=tables,
        pair_rows=pair_rows,
        summary_rows=summary_rows,
    )

    paths = {
        "pairs": bundle_dir / "cost_calibration_pairs.csv",
        "summary_table": bundle_dir / "cost_calibration_summary.csv",
        "summary": bundle_dir / "cost_calibration_summary.json",
        "boundaries": bundle_dir / "cost_calibration_boundaries.md",
    }
    write_csv(paths["pairs"], pair_rows)
    write_csv(paths["summary_table"], summary_rows)
    paths["summary"].write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    paths["boundaries"].write_text(render_cost_calibration_boundaries(summary), encoding="utf-8")
    return paths


class CostCalibrationTables:
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

    @classmethod
    def load(cls, aggregate_dir: Path) -> "CostCalibrationTables":
        return cls(
            runs=read_optional_csv(aggregate_dir / "runs.csv"),
            metrics=read_optional_csv(aggregate_dir / "metrics.csv"),
            target=read_optional_csv(aggregate_dir / "target_cost_error.csv"),
        )


def build_cost_calibration_pair_rows(
    tables: CostCalibrationTables,
) -> list[dict[str, object]]:
    runs_by_id = {row.get("run_id", ""): row for row in tables.runs}
    metrics_by_id = {row.get("run_id", ""): row for row in tables.metrics}
    rows: list[dict[str, object]] = []
    for target in tables.target:
        run_id = target.get("run_id", "")
        run = runs_by_id.get(run_id, {})
        metric = metrics_by_id.get(run_id, {})
        merged = {**target, **prefixed(run, "run_"), **prefixed(metric, "metric_")}
        rows.append(cost_calibration_pair_row(merged))
    return rows


def cost_calibration_pair_row(row: dict[str, Any]) -> dict[str, object]:
    baseline_available = truthy(row.get("baseline_available"))
    controller_extra = to_float_or_none(row.get("controller_estimated_extra_cost"))
    actual_extra = (
        to_float_or_none(row.get("actual_extra_cost_est"))
        if baseline_available
        else None
    )
    controller_minus_reported = (
        controller_extra - actual_extra
        if controller_extra is not None and actual_extra is not None
        else ""
    )
    reported_to_controller_ratio = (
        actual_extra / controller_extra
        if controller_extra not in {None, 0.0} and actual_extra is not None
        else ""
    )
    return {
        "run_id": row.get("run_id", ""),
        "experiment_name": first_present(row, "run_experiment_name", "experiment_name"),
        "repeat_index": first_present(row, "repeat_index", "run_repeat_index"),
        "repeat_label": first_present(row, "repeat_label", "run_repeat_label"),
        "task_id": row.get("task_id", ""),
        "condition": row.get("condition", ""),
        "target_level": row.get("target_level", ""),
        "agent_runtime": row.get("agent_runtime", ""),
        "model": row.get("model", ""),
        "verifier_exposure_condition": row.get("verifier_exposure_condition", ""),
        "entry_surface": row.get("entry_surface", ""),
        "usage_source": first_present(row, "run_usage_source", "metric_usage_source"),
        "cost_proxy_source": row.get("cost_proxy_source", ""),
        "target_extra_cost": row.get("target_extra_cost", ""),
        "target_extra_cost_lower": row.get("target_extra_cost_lower", ""),
        "target_extra_cost_upper": row.get("target_extra_cost_upper", ""),
        "controller_estimated_extra_cost": value_or_blank(controller_extra),
        "controller_target_interval_hit": row.get("controller_target_interval_hit", ""),
        "controller_target_cost_error": row.get("controller_target_cost_error", ""),
        "controller_overshoot": row.get("controller_overshoot", ""),
        "controller_undershoot": row.get("controller_undershoot", ""),
        "baseline_available": baseline_available,
        "actual_extra_cost_est": value_or_blank(actual_extra),
        "reported_token_target_interval_hit": row.get("target_interval_hit", ""),
        "reported_token_target_cost_error": row.get("target_cost_error", ""),
        "reported_token_overshoot": row.get("overshoot", ""),
        "reported_token_undershoot": row.get("undershoot", ""),
        "controller_minus_reported_extra_cost": controller_minus_reported,
        "reported_to_controller_extra_cost_ratio": reported_to_controller_ratio,
        "total_tokens_est": row.get("metric_total_tokens_est", ""),
        "baseline_tokens_est": row.get("metric_baseline_tokens_est", ""),
        "extra_tokens_est": row.get("metric_extra_tokens_est", ""),
        "cost_amplification_factor": row.get("metric_cost_amplification_factor", ""),
        "input_token_amplification_factor": row.get(
            "metric_input_token_amplification_factor", ""
        ),
        "output_token_amplification_factor": row.get(
            "metric_output_token_amplification_factor", ""
        ),
        "verifier_calls": first_present(row, "run_verifier_calls", "metric_verifier_calls"),
        "repair_count": row.get("repair_count", ""),
        "pagination_count": row.get("pagination_count", ""),
        "candidate_build_success": first_present(
            row, "run_candidate_build_success", "metric_candidate_build_success"
        ),
        "final_submission_seen": first_present(
            row, "run_final_submission_seen", "metric_final_submission_seen"
        ),
        "failure_label": first_present(row, "run_failure_label", "metric_failure_label"),
        "calibration_status": calibration_status(
            baseline_available=baseline_available,
            controller_hit=truthy(row.get("controller_target_interval_hit")),
            controller_overshoot=truthy(row.get("controller_overshoot")),
            controller_undershoot=truthy(row.get("controller_undershoot")),
            reported_hit=truthy(row.get("target_interval_hit")),
            reported_overshoot=truthy(row.get("overshoot")),
            reported_undershoot=truthy(row.get("undershoot")),
        ),
    }


def build_cost_calibration_summary_rows(
    pair_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    groups: dict[tuple[str, str, str, str, str, str, str], list[dict[str, object]]] = {}
    for row in pair_rows:
        groups.setdefault(cost_calibration_group_key(row), []).append(row)

    rows: list[dict[str, object]] = []
    for key, group in sorted(groups.items()):
        with_baseline = [row for row in group if truthy(row.get("baseline_available"))]
        rows.append(
            {
                "agent_runtime": key[0],
                "model": key[1],
                "verifier_exposure_condition": key[2],
                "entry_surface": key[3],
                "condition": key[4],
                "target_level": key[5],
                "cost_proxy_source": key[6],
                "runs": len(group),
                "runs_with_reported_token_baseline": len(with_baseline),
                "controller_target_interval_hit_rate": bool_rate(
                    group, "controller_target_interval_hit"
                ),
                "controller_overshoot_rate": bool_rate(group, "controller_overshoot"),
                "controller_undershoot_rate": bool_rate(group, "controller_undershoot"),
                "reported_token_target_interval_hit_rate": bool_rate(
                    with_baseline, "reported_token_target_interval_hit"
                ),
                "reported_token_overshoot_rate": bool_rate(
                    with_baseline, "reported_token_overshoot"
                ),
                "reported_token_undershoot_rate": bool_rate(
                    with_baseline, "reported_token_undershoot"
                ),
                "positive_reported_token_amplification_rate": positive_rate(
                    [row.get("extra_tokens_est") for row in with_baseline]
                ),
                "avg_controller_estimated_extra_cost": mean_present(
                    [row.get("controller_estimated_extra_cost") for row in group]
                ),
                "avg_actual_extra_cost_est": mean_present(
                    [row.get("actual_extra_cost_est") for row in with_baseline]
                ),
                "avg_controller_minus_reported_extra_cost": mean_present(
                    [row.get("controller_minus_reported_extra_cost") for row in with_baseline]
                ),
                "avg_controller_target_cost_error": mean_present(
                    [row.get("controller_target_cost_error") for row in group]
                ),
                "avg_reported_token_target_cost_error": mean_present(
                    [row.get("reported_token_target_cost_error") for row in with_baseline]
                ),
                "avg_cost_amplification_factor": mean_present(
                    [row.get("cost_amplification_factor") for row in with_baseline]
                ),
                "avg_extra_tokens_est": mean_present(
                    [row.get("extra_tokens_est") for row in with_baseline]
                ),
                "avg_verifier_calls": mean_present([row.get("verifier_calls") for row in group]),
                "runs_with_repair": sum(
                    1 for row in group if to_float_or_none(row.get("repair_count")) not in {None, 0.0}
                ),
                "runs_with_pagination": sum(
                    1
                    for row in group
                    if to_float_or_none(row.get("pagination_count")) not in {None, 0.0}
                ),
                "usage_sources": join_sorted(
                    {str(row.get("usage_source", "")) for row in group}
                ),
                "calibration_statuses": summarize_statuses(group),
                "interpretation": interpret_calibration_group(group),
            }
        )
    return rows


def build_cost_calibration_summary(
    *,
    run_dir: Path,
    tables: CostCalibrationTables,
    pair_rows: list[dict[str, object]],
    summary_rows: list[dict[str, object]],
) -> dict[str, Any]:
    with_baseline = [row for row in pair_rows if truthy(row.get("baseline_available"))]
    return {
        "run_dir": str(run_dir),
        "source_runs": len(tables.runs),
        "target_rows": len(tables.target),
        "pair_rows": len(pair_rows),
        "summary_rows": len(summary_rows),
        "runs_with_reported_token_baseline": len(with_baseline),
        "controller_target_interval_hit_rate": bool_rate(
            pair_rows, "controller_target_interval_hit"
        ),
        "reported_token_target_interval_hit_rate": bool_rate(
            with_baseline, "reported_token_target_interval_hit"
        ),
        "controller_overshoot_rate": bool_rate(pair_rows, "controller_overshoot"),
        "controller_undershoot_rate": bool_rate(pair_rows, "controller_undershoot"),
        "reported_token_overshoot_rate": bool_rate(with_baseline, "reported_token_overshoot"),
        "reported_token_undershoot_rate": bool_rate(
            with_baseline, "reported_token_undershoot"
        ),
        "avg_controller_estimated_extra_cost": mean_present(
            [row.get("controller_estimated_extra_cost") for row in pair_rows]
        ),
        "avg_actual_extra_cost_est": mean_present(
            [row.get("actual_extra_cost_est") for row in with_baseline]
        ),
        "avg_controller_minus_reported_extra_cost": mean_present(
            [row.get("controller_minus_reported_extra_cost") for row in with_baseline]
        ),
        "cost_proxy_sources": join_sorted(
            {str(row.get("cost_proxy_source", "")) for row in pair_rows}
        ).split(";")
        if pair_rows
        else [],
        "usage_sources": join_sorted(
            {str(row.get("usage_source", "")) for row in pair_rows}
        ).split(";")
        if pair_rows
        else [],
        "calibration_status_counts": dict(
            sorted(
                Counter(str(row.get("calibration_status", "")) for row in pair_rows).items()
            )
        ),
        "artifact_scope": (
            "Controller proxy calibration and reported-token target fit are reported "
            "as separate evidence channels."
        ),
    }


def render_cost_calibration_boundaries(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Cost Calibration Boundaries",
            "",
            "This bundle reads existing aggregate CSV files. It does not run new agent experiments.",
            "",
            f"- source runs: {summary['source_runs']}",
            f"- target rows: {summary['target_rows']}",
            f"- runs with reported-token baseline: {summary['runs_with_reported_token_baseline']}",
            "",
            "## Interpretation",
            "",
            "- `controller_*` fields describe the internal budget proxy used by the verifier controller.",
            "- `reported_token_*` fields describe observed token cost relative to a paired clean/no-attack baseline.",
            "- A controller target hit must not be reported as a reported-token target hit.",
            f"- {summary['artifact_scope']}",
            "",
        ]
    )


def calibration_status(
    *,
    baseline_available: bool,
    controller_hit: bool,
    controller_overshoot: bool,
    controller_undershoot: bool,
    reported_hit: bool,
    reported_overshoot: bool,
    reported_undershoot: bool,
) -> str:
    controller_state = interval_label(
        hit=controller_hit,
        overshoot=controller_overshoot,
        undershoot=controller_undershoot,
    )
    if not baseline_available:
        return f"controller_{controller_state}_reported_unavailable"
    reported_state = interval_label(
        hit=reported_hit,
        overshoot=reported_overshoot,
        undershoot=reported_undershoot,
    )
    return f"controller_{controller_state}_reported_{reported_state}"


def interval_label(*, hit: bool, overshoot: bool, undershoot: bool) -> str:
    if hit:
        return "hit"
    if overshoot:
        return "overshoot"
    if undershoot:
        return "undershoot"
    return "off_target"


def interpret_calibration_group(group: list[dict[str, object]]) -> str:
    controller_hit = bool_rate(group, "controller_target_interval_hit")
    with_baseline = [row for row in group if truthy(row.get("baseline_available"))]
    reported_hit = bool_rate(with_baseline, "reported_token_target_interval_hit")
    return (
        f"controller_hit_rate={format_rate(controller_hit)}; "
        f"reported_token_hit_rate={format_rate(reported_hit)}; "
        "interpret the two rates separately"
    )


def cost_calibration_group_key(
    row: dict[str, object],
) -> tuple[str, str, str, str, str, str, str]:
    return (
        str(row.get("agent_runtime", "")),
        str(row.get("model", "")),
        str(row.get("verifier_exposure_condition", "")),
        str(row.get("entry_surface", "")),
        str(row.get("condition", "")),
        str(row.get("target_level", "")),
        str(row.get("cost_proxy_source", "")),
    )


def summarize_statuses(rows: list[dict[str, object]]) -> str:
    counts = Counter(str(row.get("calibration_status", "")) for row in rows)
    return ";".join(f"{status}:{count}" for status, count in sorted(counts.items()))


def prefixed(row: dict[str, str], prefix: str) -> dict[str, str]:
    return {f"{prefix}{key}": value for key, value in row.items()}


def read_optional_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    return read_csv_dicts(path)


def first_present(row: dict[str, Any], *keys: str) -> object:
    for key in keys:
        value = row.get(key)
        if value_present(value):
            return value
    return ""


def value_present(value: object) -> bool:
    if value is None:
        return False
    return str(value).strip() not in {"", "None", "none", "null"}


def value_or_blank(value: float | None) -> float | str:
    return value if value is not None else ""


def to_float_or_none(value: object) -> float | None:
    try:
        if not value_present(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def truthy(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def bool_rate(rows: list[dict[str, object]], field: str) -> float | str:
    observed = [row for row in rows if value_present(row.get(field))]
    return ratio(sum(1 for row in observed if truthy(row.get(field))), len(observed))


def positive_rate(values: list[object]) -> float | str:
    parsed = [value for value in (to_float_or_none(item) for item in values) if value is not None]
    return ratio(sum(1 for value in parsed if value > 0), len(parsed))


def mean_present(values: list[object]) -> float | str:
    parsed = [value for value in (to_float_or_none(item) for item in values) if value is not None]
    return sum(parsed) / len(parsed) if parsed else ""


def ratio(numerator: int | float, denominator: int) -> float | str:
    return numerator / denominator if denominator else ""


def join_sorted(values: set[str]) -> str:
    return ";".join(sorted(value for value in values if value))


def format_rate(value: object) -> str:
    if value == "":
        return "n/a"
    parsed = to_float_or_none(value)
    return "n/a" if parsed is None else f"{parsed:.6g}"
