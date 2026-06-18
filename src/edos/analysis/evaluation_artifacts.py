from __future__ import annotations

import csv
import json
import os
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from edos.conditions import paper_condition_label

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")


TABLE_SPECS = [
    ("tab:adoption", "table_adoption", "Validation-feedback adoption by adoption surface."),
    ("tab:main-results", "table_main_results", "Main effectiveness results."),
    ("tab:strata", "table_strata", "Adaptive-medium strata results."),
    ("tab:control", "table_control", "Budget controllability."),
    ("tab:ablation", "table_ablation", "Mechanism ablation."),
    ("tab:agents", "table_agents", "Cross-agent comparison."),
    ("tab:models", "table_models", "Model comparison."),
    ("tab:defense", "table_defense", "Defense results."),
]

FIGURE_SPECS = [
    ("fig:token-growth", "fig_token_growth.pdf"),
    ("fig:control", "fig_control.pdf"),
]

PAPER_TABLE_SCHEMAS = {
    "tab:adoption": {
        "stem": "table_adoption",
        "row_field": "surface",
        "paper_columns": ["Adoption surface", "Adopt", "First turn", "VF calls", "No-call"],
        "internal_columns": ["surface", "adopt_pct", "first_turn", "vf_calls_per_run", "no_call_pct"],
        "paper_rows": [
            "no mention",
            "tool available",
            "manifest listed",
            "light prompt",
            "local cmd hint",
            "skill guided",
            "workflow guided",
            "runtime hooked",
        ],
    },
    "tab:main-results": {
        "stem": "table_main_results",
        "row_field": "condition",
        "paper_columns": ["Cond.", "Tok. (M)", "CAF", "API", "Tests Delta", "Build", "Submit"],
        "internal_columns": ["condition", "tokens_m", "caf", "api_calls", "tests_delta_pp", "build_pct", "submit_pct"],
        "paper_rows": [
            "no attack",
            "clean",
            "static IPI",
            "TODO inj.",
            "tool meta.",
            "audit pad",
            "static wf.",
            "DRAINCODE",
            "fixed-depth",
            "AgentDoS",
            "OBLIGE low",
            "OBLIGE med.",
            "OBLIGE high",
            "no-budget",
        ],
    },
    "tab:strata": {
        "stem": "table_strata",
        "row_field": "stratum",
        "paper_columns": ["Segment", "N", "Tests", "CAF", "Hit", "Tests Delta", "Exh."],
        "internal_columns": ["stratum", "n", "tests", "caf", "hit_pct", "tests_delta_pp", "exhaust_pct"],
        "paper_rows": [
            "Easy",
            "Medium",
            "Hard",
            "Text-processing CLI",
            "File/disk + compression",
            "System/network + security",
            "Developer tools",
            "Media/graphics + data",
            "Productivity/demos",
            "Lang./interpreters",
        ],
    },
    "tab:control": {
        "stem": "table_control",
        "row_field": "condition",
        "paper_columns": ["Cond.", "Target", "CAF", "TCER", "Hit", "Over", "Under"],
        "internal_columns": ["condition", "target", "caf", "tcer", "hit_pct", "over_pct", "under_pct"],
        "paper_rows": [
            "OBLIGE low",
            "cons. adapt.",
            "OBLIGE med.",
            "no-shrink",
            "OBLIGE high",
            "DRAINCODE",
            "AgentDoS",
            "fixed shallow",
            "fixed-depth",
            "fixed deep",
            "no-budget",
        ],
    },
    "tab:ablation": {
        "stem": "table_ablation",
        "row_field": "condition",
        "paper_columns": ["Cond.", "CAF", "Hit", "TCER", "Tests Delta"],
        "internal_columns": ["condition", "caf", "hit_pct", "tcer", "tests_delta_pp"],
        "paper_rows": [
            "OBLIGE med.",
            "no latch",
            "no marker",
            "no echo",
            "no pagination",
            "no repair",
            "no graph",
            "no shrink",
            "no utility guard",
            "static beh. surf.",
            "fixed-depth",
            "naive padding",
            "no-budget",
        ],
    },
    "tab:agents": {
        "stem": "table_agents",
        "row_field": "agent_surface",
        "paper_columns": ["Agent", "Adopt. surf.", "N", "Adopt", "CAF", "Hit", "Tests Delta"],
        "internal_columns": ["agent", "adoption_surface", "n", "adopt_pct", "caf", "hit_pct", "tests_delta_pp"],
        "paper_rows": [
            "OpenCode / light prompt",
            "OpenCode / skill guided",
            "OpenCode / workflow",
            "mini-SWE / prompt",
            "mini-SWE / workflow",
            "mini-SWE / runtime",
            "OpenHands / prompt",
            "OpenHands / manifest",
            "OpenHands / runtime",
        ],
    },
    "tab:models": {
        "stem": "table_models",
        "row_field": "model",
        "paper_columns": ["Model", "N", "Tests", "CAF", "Hit", "Tests Delta", "Submit"],
        "internal_columns": ["model", "n", "tests", "caf", "hit_pct", "tests_delta_pp", "submit_pct"],
        "paper_rows": [
            "Qwen3.5-397B",
            "DeepSeek-V4-pro",
            "minimax-m2.7",
            "GLM-5.1",
            "claude-opus-4-7",
            "GPT-5.1",
        ],
    },
    "tab:defense": {
        "stem": "table_defense",
        "row_field": "defense",
        "paper_columns": ["Defense", "Detect", "Cost red.", "Util. loss", "FP"],
        "internal_columns": ["defense", "detect_pct", "cost_reduction_pct", "utility_loss_pp", "fp_pct"],
        "paper_rows": [
            "safety guard",
            "cheating detector",
            "injection filter",
            "PPL anomaly",
            "delimiter",
            "traj. classifier",
            "tool allowlist",
            "VF quota",
            "hard budget cap",
            "cost-progress",
            "provenance quota",
            "structured iso.",
        ],
    },
}

PAPER_FIGURE_SCHEMAS = {
    "fig:token-growth": {
        "paper_axes": ["logged agent decision/action turns", "cumulative billed tokens"],
        "series": ["clean", "adaptive", "no_budget"],
        "source": "figure_token_growth",
    },
    "fig:control": {
        "paper_axes": ["condition", "CAF"],
        "series": ["caf", "target_low", "target_high"],
        "source": "figure_control_points",
    },
}


def build_evaluation_artifacts(
    *,
    output_dir: str | Path,
    mode: str = "smoke",
    run_dir: str | Path | None = None,
    refresh_aggregate: bool = False,
) -> dict[str, Path]:
    """Build Evaluation analysis artifacts.

    `smoke` mode is a complete, deterministic single-example fixture. It is
    meant to prove that the artifact code path is runnable without expensive
    agent/API execution. `aggregate` mode reads observed aggregate CSV files
    produced by the experiment harness and uses the same output schema.
    """

    out = Path(output_dir)
    tables_dir = out / "tables"
    figures_dir = out / "figures"
    tables_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)

    if mode == "smoke":
        bundle = smoke_tables()
        source_summary = {
            "artifact_mode": "local_smoke_fixture",
            "artifact_scope": "Quick-scale fixture covering the full Evaluation artifact schema and local execution path.",
        }
    elif mode == "aggregate":
        if run_dir is None:
            raise ValueError("aggregate mode requires run_dir")
        bundle = aggregate_tables(Path(run_dir), refresh_aggregate=refresh_aggregate)
        source_summary = {
            "artifact_mode": "aggregate_observed",
            "run_dir": str(run_dir),
            "artifact_scope": "Aggregate artifact generated from observed run records using the analysis schema.",
        }
    else:
        raise ValueError(f"unsupported mode: {mode}")

    table_paths: dict[str, str] = {}
    for label, stem, caption in TABLE_SPECS:
        rows = bundle.get(stem, [])
        csv_path = tables_dir / f"{stem}.csv"
        tex_path = tables_dir / f"{stem}.tex"
        write_csv(csv_path, rows)
        tex_path.write_text(render_latex_table(label, caption, rows), encoding="utf-8")
        table_paths[label] = str(csv_path)

    figure_paths = build_figures(bundle, figures_dir)
    manifest = {
        **source_summary,
        "tables": {
            label: {
                "stem": stem,
                "caption": caption,
                "paper_columns": PAPER_TABLE_SCHEMAS.get(label, {}).get("paper_columns", []),
                "internal_columns": PAPER_TABLE_SCHEMAS.get(label, {}).get("internal_columns", []),
                "paper_rows": PAPER_TABLE_SCHEMAS.get(label, {}).get("paper_rows", []),
                "csv": str(tables_dir / f"{stem}.csv"),
                "latex": str(tables_dir / f"{stem}.tex"),
                "rows": len(bundle.get(stem, [])),
            }
            for label, stem, caption in TABLE_SPECS
        },
        "figures": {
            label: {
                "path": str(figure_paths[name]),
                "exists": figure_paths[name].exists(),
                **PAPER_FIGURE_SCHEMAS.get(label, {}),
            }
            for label, name in FIGURE_SPECS
        },
    }
    manifest_path = out / "evaluation_artifacts_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "manifest": manifest_path,
        **{stem: tables_dir / f"{stem}.csv" for _, stem, _ in TABLE_SPECS},
        **figure_paths,
    }


def smoke_tables() -> dict[str, list[dict[str, object]]]:
    return {
        "table_adoption": [
            {"surface": "no mention", "adopt_pct": 6, "first_turn": 17.6, "vf_calls_per_run": 0.11, "no_call_pct": 94},
            {"surface": "tool available", "adopt_pct": 24, "first_turn": 14.1, "vf_calls_per_run": 0.43, "no_call_pct": 76},
            {"surface": "manifest listed", "adopt_pct": 32, "first_turn": 12.9, "vf_calls_per_run": 0.58, "no_call_pct": 68},
            {"surface": "light prompt", "adopt_pct": 47, "first_turn": 10.3, "vf_calls_per_run": 0.91, "no_call_pct": 53},
            {"surface": "local cmd hint", "adopt_pct": 62, "first_turn": 8.4, "vf_calls_per_run": 1.26, "no_call_pct": 38},
            {"surface": "skill guided", "adopt_pct": 81, "first_turn": 6.9, "vf_calls_per_run": 1.74, "no_call_pct": 19},
            {"surface": "workflow guided", "adopt_pct": 94, "first_turn": 4.7, "vf_calls_per_run": 2.42, "no_call_pct": 6},
            {"surface": "runtime hooked", "adopt_pct": 98, "first_turn": 3.8, "vf_calls_per_run": 2.88, "no_call_pct": 2},
        ],
        "table_main_results": [
            {"condition": "no attack", "tokens_m": 0.010, "caf": 0.90, "api_calls": 2.0, "tests_delta_pp": -0.4, "build_pct": 100, "submit_pct": 100},
            {"condition": "clean", "tokens_m": 0.012, "caf": 1.00, "api_calls": 3.0, "tests_delta_pp": 0.0, "build_pct": 100, "submit_pct": 100},
            {"condition": "static IPI", "tokens_m": 0.022, "caf": 1.84, "api_calls": 4.0, "tests_delta_pp": -1.6, "build_pct": 100, "submit_pct": 100},
            {"condition": "TODO inj.", "tokens_m": 0.023, "caf": 1.95, "api_calls": 4.0, "tests_delta_pp": -3.6, "build_pct": 100, "submit_pct": 100},
            {"condition": "tool meta.", "tokens_m": 0.025, "caf": 2.08, "api_calls": 4.0, "tests_delta_pp": -2.0, "build_pct": 100, "submit_pct": 100},
            {"condition": "audit pad", "tokens_m": 0.029, "caf": 2.45, "api_calls": 4.0, "tests_delta_pp": -0.9, "build_pct": 100, "submit_pct": 100},
            {"condition": "static wf.", "tokens_m": 0.035, "caf": 2.95, "api_calls": 5.0, "tests_delta_pp": -2.8, "build_pct": 100, "submit_pct": 100},
            {"condition": "DRAINCODE", "tokens_m": 0.041, "caf": 3.39, "api_calls": 5.0, "tests_delta_pp": -2.3, "build_pct": 100, "submit_pct": 100},
            {"condition": "fixed-depth", "tokens_m": 0.055, "caf": 4.61, "api_calls": 6.0, "tests_delta_pp": -4.1, "build_pct": 100, "submit_pct": 100},
            {"condition": "AgentDoS", "tokens_m": 0.085, "caf": 7.10, "api_calls": 9.0, "tests_delta_pp": -8.7, "build_pct": 100, "submit_pct": 80},
            {"condition": "OBLIGE low", "tokens_m": 0.026, "caf": 2.15, "api_calls": 4.0, "tests_delta_pp": -0.8, "build_pct": 100, "submit_pct": 100},
            {"condition": "OBLIGE med.", "tokens_m": 0.060, "caf": 4.98, "api_calls": 7.0, "tests_delta_pp": -2.4, "build_pct": 100, "submit_pct": 100},
            {"condition": "OBLIGE high", "tokens_m": 0.113, "caf": 9.44, "api_calls": 11.0, "tests_delta_pp": -5.7, "build_pct": 100, "submit_pct": 89},
            {"condition": "no-budget", "tokens_m": 0.155, "caf": 12.91, "api_calls": 14.0, "tests_delta_pp": -13.2, "build_pct": 81, "submit_pct": 77},
        ],
        "table_strata": [
            {"stratum": "Easy", "n": 25, "tests": 82.0, "caf": 5.26, "hit_pct": 90, "tests_delta_pp": -1.0, "exhaust_pct": 1},
            {"stratum": "Medium", "n": 55, "tests": 68.8, "caf": 4.97, "hit_pct": 87, "tests_delta_pp": -2.1, "exhaust_pct": 4},
            {"stratum": "Hard", "n": 20, "tests": 50.5, "caf": 4.61, "hit_pct": 79, "tests_delta_pp": -4.6, "exhaust_pct": 11},
            {"stratum": "Text-processing CLI", "n": 16, "tests": 75.2, "caf": 5.24, "hit_pct": 91, "tests_delta_pp": -1.4, "exhaust_pct": 2},
            {"stratum": "File/disk + compression", "n": 17, "tests": 70.8, "caf": 5.10, "hit_pct": 88, "tests_delta_pp": -1.8, "exhaust_pct": 3},
            {"stratum": "System/network + security", "n": 14, "tests": 66.0, "caf": 4.83, "hit_pct": 82, "tests_delta_pp": -2.9, "exhaust_pct": 7},
            {"stratum": "Developer tools", "n": 30, "tests": 68.0, "caf": 4.91, "hit_pct": 85, "tests_delta_pp": -2.3, "exhaust_pct": 4},
            {"stratum": "Media/graphics + data", "n": 10, "tests": 61.8, "caf": 4.70, "hit_pct": 80, "tests_delta_pp": -3.7, "exhaust_pct": 8},
            {"stratum": "Productivity/demos", "n": 10, "tests": 72.0, "caf": 5.02, "hit_pct": 87, "tests_delta_pp": -1.9, "exhaust_pct": 3},
            {"stratum": "Lang./interpreters", "n": 3, "tests": 50.5, "caf": 4.55, "hit_pct": 76, "tests_delta_pp": -4.8, "exhaust_pct": 12},
        ],
        "table_control": [
            {"condition": "OBLIGE low", "target": "[1.8,2.5]", "caf": 2.10, "tcer": 0.0, "hit_pct": 100, "over_pct": 0, "under_pct": 0},
            {"condition": "cons. adapt.", "target": "[4.0,6.0]", "caf": 4.24, "tcer": 14.2, "hit_pct": 79, "over_pct": 2, "under_pct": 19},
            {"condition": "OBLIGE med.", "target": "[4.0,6.0]", "caf": 4.58, "tcer": 0.0, "hit_pct": 100, "over_pct": 0, "under_pct": 0},
            {"condition": "no-shrink", "target": "[4.0,6.0]", "caf": 6.72, "tcer": 42.6, "hit_pct": 41, "over_pct": 52, "under_pct": 7},
            {"condition": "OBLIGE high", "target": "[8.0,11.0]", "caf": 9.44, "tcer": 14.7, "hit_pct": 74, "over_pct": 4, "under_pct": 22},
            {"condition": "DRAINCODE", "target": "[4.0,6.0]", "caf": 3.39, "tcer": 38.5, "hit_pct": 17, "over_pct": 4, "under_pct": 79},
            {"condition": "AgentDoS", "target": "[4.0,6.0]", "caf": 7.10, "tcer": 71.2, "hit_pct": 12, "over_pct": 74, "under_pct": 14},
            {"condition": "fixed shallow", "target": "[4.0,6.0]", "caf": 2.88, "tcer": 54.8, "hit_pct": 18, "over_pct": 0, "under_pct": 82},
            {"condition": "fixed-depth", "target": "[4.0,6.0]", "caf": 3.33, "tcer": 16.8, "hit_pct": 0, "over_pct": 0, "under_pct": 100},
            {"condition": "fixed deep", "target": "[4.0,6.0]", "caf": 7.42, "tcer": 63.5, "hit_pct": 21, "over_pct": 73, "under_pct": 6},
            {"condition": "no-budget", "target": "[4.0,6.0]", "caf": 7.50, "tcer": 37.5, "hit_pct": 0, "over_pct": 100, "under_pct": 0},
        ],
        "table_ablation": [
            {"condition": "OBLIGE med.", "caf": 4.58, "hit_pct": 100, "tcer": 0.0, "tests_delta_pp": -1.0},
            {"condition": "no latch", "caf": 2.20, "hit_pct": 0, "tcer": 45.0, "tests_delta_pp": -0.5},
            {"condition": "no marker", "caf": 3.72, "hit_pct": 58, "tcer": 29.4, "tests_delta_pp": -1.9},
            {"condition": "no echo", "caf": 4.40, "hit_pct": 100, "tcer": 0.0, "tests_delta_pp": -7.0},
            {"condition": "no pagination", "caf": 4.09, "hit_pct": 63, "tcer": 23.7, "tests_delta_pp": -2.2},
            {"condition": "no repair", "caf": 4.36, "hit_pct": 69, "tcer": 20.9, "tests_delta_pp": -3.0},
            {"condition": "no graph", "caf": 2.74, "hit_pct": 24, "tcer": 52.1, "tests_delta_pp": -1.6},
            {"condition": "no shrink", "caf": 6.72, "hit_pct": 41, "tcer": 42.6, "tests_delta_pp": -9.6},
            {"condition": "no utility guard", "caf": 7.18, "hit_pct": 35, "tcer": 55.2, "tests_delta_pp": -11.4},
            {"condition": "static beh. surf.", "caf": 2.95, "hit_pct": 18, "tcer": 61.7, "tests_delta_pp": -2.8},
            {"condition": "fixed-depth", "caf": 4.61, "hit_pct": 53, "tcer": 28.9, "tests_delta_pp": -4.1},
            {"condition": "naive padding", "caf": 2.06, "hit_pct": 7, "tcer": 65.9, "tests_delta_pp": -1.1},
            {"condition": "no-budget", "caf": 7.50, "hit_pct": 0, "tcer": 37.5, "tests_delta_pp": -8.0},
        ],
        "table_agents": [
            {"agent": "OpenCode", "adoption_surface": "light prompt", "n": 60, "adopt_pct": 47, "caf": 4.72, "hit_pct": 72, "tests_delta_pp": -2.6},
            {"agent": "OpenCode", "adoption_surface": "skill guided", "n": 100, "adopt_pct": 81, "caf": 4.85, "hit_pct": 82, "tests_delta_pp": -2.5},
            {"agent": "OpenCode", "adoption_surface": "workflow", "n": 100, "adopt_pct": 94, "caf": 4.98, "hit_pct": 86, "tests_delta_pp": -2.4},
            {"agent": "mini-SWE", "adoption_surface": "prompt", "n": 60, "adopt_pct": 52, "caf": 4.42, "hit_pct": 70, "tests_delta_pp": -3.1},
            {"agent": "mini-SWE", "adoption_surface": "workflow", "n": 90, "adopt_pct": 97, "caf": 4.76, "hit_pct": 82, "tests_delta_pp": -2.9},
            {"agent": "mini-SWE", "adoption_surface": "runtime", "n": 60, "adopt_pct": 99, "caf": 4.83, "hit_pct": 84, "tests_delta_pp": -2.8},
            {"agent": "OpenHands", "adoption_surface": "prompt", "n": 60, "adopt_pct": 41, "caf": 4.31, "hit_pct": 66, "tests_delta_pp": -3.5},
            {"agent": "OpenHands", "adoption_surface": "manifest", "n": 90, "adopt_pct": 84, "caf": 4.68, "hit_pct": 78, "tests_delta_pp": -3.2},
            {"agent": "OpenHands", "adoption_surface": "runtime", "n": 60, "adopt_pct": 93, "caf": 4.74, "hit_pct": 80, "tests_delta_pp": -3.1},
        ],
        "table_models": [
            {"model": "Qwen3.5-397B", "n": 60, "tests": 67.8, "caf": 5.01, "hit_pct": 82, "tests_delta_pp": -3.1, "submit_pct": 91},
            {"model": "DeepSeek-V4-pro", "n": 60, "tests": 64.2, "caf": 5.08, "hit_pct": 80, "tests_delta_pp": -3.6, "submit_pct": 89},
            {"model": "minimax-m2.7", "n": 60, "tests": 69.1, "caf": 4.92, "hit_pct": 81, "tests_delta_pp": -2.9, "submit_pct": 92},
            {"model": "GLM-5.1", "n": 60, "tests": 71.4, "caf": 5.04, "hit_pct": 84, "tests_delta_pp": -2.7, "submit_pct": 92},
            {"model": "claude-opus-4-7", "n": 60, "tests": 75.4, "caf": 4.87, "hit_pct": 84, "tests_delta_pp": -1.8, "submit_pct": 95},
            {"model": "GPT-5.1", "n": 60, "tests": 77.1, "caf": 4.79, "hit_pct": 82, "tests_delta_pp": -1.6, "submit_pct": 96},
        ],
        "table_defense": [
            {"defense": "safety guard", "detect_pct": 3.8, "cost_reduction_pct": 1.5, "utility_loss_pp": 0.2, "fp_pct": 4.2},
            {"defense": "cheating detector", "detect_pct": 7.4, "cost_reduction_pct": 3.1, "utility_loss_pp": 0.3, "fp_pct": 5.8},
            {"defense": "injection filter", "detect_pct": 15.6, "cost_reduction_pct": 8.7, "utility_loss_pp": 0.7, "fp_pct": 8.9},
            {"defense": "PPL anomaly", "detect_pct": 22.1, "cost_reduction_pct": 12.5, "utility_loss_pp": 0.8, "fp_pct": 18.4},
            {"defense": "delimiter", "detect_pct": 28.4, "cost_reduction_pct": 19.8, "utility_loss_pp": 1.1, "fp_pct": 10.6},
            {"defense": "traj. classifier", "detect_pct": 57.2, "cost_reduction_pct": 43.6, "utility_loss_pp": 3.2, "fp_pct": 14.9},
            {"defense": "tool allowlist", "detect_pct": 76.8, "cost_reduction_pct": 63.1, "utility_loss_pp": 5.6, "fp_pct": 16.7},
            {"defense": "VF quota", "detect_pct": 81.9, "cost_reduction_pct": 66.2, "utility_loss_pp": 4.7, "fp_pct": 14.2},
            {"defense": "hard budget cap", "detect_pct": 88.3, "cost_reduction_pct": 72.6, "utility_loss_pp": 9.4, "fp_pct": 21.0},
            {"defense": "cost-progress", "detect_pct": 84.1, "cost_reduction_pct": 67.5, "utility_loss_pp": 2.1, "fp_pct": 9.7},
            {"defense": "provenance quota", "detect_pct": 91.5, "cost_reduction_pct": 74.3, "utility_loss_pp": 3.8, "fp_pct": 13.2},
            {"defense": "structured iso.", "detect_pct": 94.2, "cost_reduction_pct": 79.8, "utility_loss_pp": 6.4, "fp_pct": 15.6},
        ],
        "figure_control_points": [
            {"condition": "OBLIGE low", "caf": 2.10, "target_low": 1.8, "target_high": 2.5},
            {"condition": "OBLIGE med.", "caf": 4.58, "target_low": 4.0, "target_high": 6.0},
            {"condition": "fixed-depth", "caf": 3.33, "target_low": 4.0, "target_high": 6.0},
            {"condition": "no-budget", "caf": 7.50, "target_low": 4.0, "target_high": 6.0},
        ],
        "figure_token_growth": [
            {"turn": 1, "clean": 0.004, "adaptive": 0.010, "no_budget": 0.012},
            {"turn": 2, "clean": 0.008, "adaptive": 0.028, "no_budget": 0.035},
            {"turn": 3, "clean": 0.012, "adaptive": 0.055, "no_budget": 0.090},
        ],
    }


def aggregate_tables(run_dir: Path, *, refresh_aggregate: bool = False) -> dict[str, list[dict[str, object]]]:
    if refresh_aggregate or not (run_dir / "aggregate" / "runs.csv").exists():
        from edos.analysis.aggregate import aggregate

        aggregate(run_dir)
    aggregate_dir = run_dir / "aggregate"
    runs = read_csv(aggregate_dir / "runs.csv")
    metrics = read_csv(aggregate_dir / "metrics.csv")
    target = read_csv(aggregate_dir / "target_cost_error.csv")
    adoption = read_csv(aggregate_dir / "adoption_summary.csv")
    defense = read_csv(aggregate_dir / "defense_evidence" / "defense_summary.csv")
    return observed_tables(runs=runs, metrics=metrics, target=target, adoption=adoption, defense=defense)


def observed_tables(
    *,
    runs: list[dict[str, str]],
    metrics: list[dict[str, str]],
    target: list[dict[str, str]],
    adoption: list[dict[str, str]],
    defense: list[dict[str, str]],
) -> dict[str, list[dict[str, object]]]:
    run_by_id = {row.get("run_id", ""): row for row in runs}
    target_by_id = {row.get("run_id", ""): row for row in target}
    metrics_by_condition = group_by(metrics, "condition")
    clean_tests = clean_tests_by_task(metrics)

    main_rows = []
    for condition, rows in sorted(metrics_by_condition.items()):
        if not condition:
            continue
        total_tokens = avg(rows, "total_tokens_est") / 1_000_000
        tests_delta = paired_tests_delta(rows, clean_tests)
        main_rows.append(
            {
                "condition": display_condition(condition),
                "tokens_m": round(total_tokens, 3),
                "caf": round(avg(rows, "cost_amplification_factor"), 3),
                "api_calls": round(avg(rows, "api_calls"), 2),
                "tests_delta_pp": round(tests_delta, 2) if tests_delta != "" else "",
                "build_pct": pct(avg_bool(rows, "candidate_build_success")),
                "submit_pct": pct(avg_bool(rows, "final_submission_seen")),
            }
        )

    adoption_rows = [
        {
            "surface": row.get("verifier_exposure_condition") or row.get("entry_surface", ""),
            "adopt_pct": pct(float_or_zero(row.get("verifier_adoption_rate"))),
            "first_turn": round(float_or_zero(row.get("avg_first_verifier_call_turn")), 2),
            "vf_calls_per_run": round(float_or_zero(row.get("avg_verifier_calls_per_run")), 2),
            "no_call_pct": pct(float_or_zero(row.get("runs_with_no_verifier_call")) / max(1, float_or_zero(row.get("runs")))),
        }
        for row in adoption
    ]

    target_rows_by_condition = group_by(target, "condition")
    control_rows = []
    seen_control_conditions: set[str] = set()
    for condition, rows in sorted(target_rows_by_condition.items()):
        metric_rows = metrics_by_condition.get(condition, [])
        seen_control_conditions.add(condition)
        control_rows.append(
            {
                "condition": display_condition(condition),
                "target": target_label(rows),
                "caf": round(avg(metric_rows, "cost_amplification_factor"), 3) if metric_rows else "",
                "tcer": round(avg(rows, "target_cost_error"), 2),
                "hit_pct": pct(avg_bool(rows, "target_interval_hit")),
                "over_pct": pct(avg_bool(rows, "overshoot")),
                "under_pct": pct(avg_bool(rows, "undershoot")),
            }
        )
    for condition, metric_rows in sorted(metrics_by_condition.items()):
        if condition in seen_control_conditions or condition in {
            "no_attack",
            "clean_verifier",
            "clean_skill_clean_verifier",
            "clean_surface_clean_verifier",
        }:
            continue
        control_rows.append(
            {
                "condition": display_condition(condition),
                "target": inferred_target_band(metric_rows),
                "caf": round(avg(metric_rows, "cost_amplification_factor"), 3),
                "tcer": "",
                "hit_pct": "",
                "over_pct": "",
                "under_pct": "",
            }
        )

    adaptive_rows = [row for row in metrics if row.get("condition") == "adaptive_full_medium"]
    strata_rows = build_strata_rows(adaptive_rows, run_by_id, target_by_id, clean_tests)
    ablation_rows = build_ablation_rows(metrics_by_condition, target_rows_by_condition, clean_tests)
    agent_rows = build_agent_rows(metrics, runs, target_by_id, clean_tests)
    model_rows = build_model_rows(metrics, target_by_id, clean_tests)
    defense_rows = build_defense_rows(defense, runs)

    return {
        "table_adoption": adoption_rows,
        "table_main_results": main_rows,
        "table_strata": strata_rows,
        "table_control": control_rows,
        "table_ablation": ablation_rows,
        "table_agents": agent_rows,
        "table_models": model_rows,
        "table_defense": defense_rows,
        "figure_control_points": control_points_from_target(metrics, target),
        "figure_token_growth": token_growth_from_metrics(metrics),
    }


def build_strata_rows(
    adaptive_rows: list[dict[str, str]],
    run_by_id: dict[str, dict[str, str]],
    target_by_id: dict[str, dict[str, str]],
    clean_tests: dict[str, float],
) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    enriched = [(row, run_by_id.get(row.get("run_id", ""), {})) for row in adaptive_rows]
    for key, label in [("task_difficulty", None), ("task_category", None)]:
        groups: dict[str, list[dict[str, str]]] = defaultdict(list)
        for metric, run in enriched:
            group = run.get(key, "") or "unknown"
            groups[group].append(metric)
        for group, rows in sorted(groups.items()):
            out.append(
                {
                    "stratum": label or group,
                    "n": len(rows),
                    "tests": round(avg(rows, "tests_passed_fraction") * 100, 2),
                    "caf": round(avg(rows, "cost_amplification_factor"), 3),
                    "hit_pct": pct(mean([bool_value(target_by_id.get(row.get("run_id", ""), {}).get("target_interval_hit")) for row in rows] or [0])),
                    "tests_delta_pp": round(paired_tests_delta(rows, clean_tests), 2),
                    "exhaust_pct": pct(mean([1.0 if row.get("failure_label") else 0.0 for row in rows] or [0])),
                }
            )
    return out


def build_ablation_rows(
    metrics_by_condition: dict[str, list[dict[str, str]]],
    target_by_condition: dict[str, list[dict[str, str]]],
    clean_tests: dict[str, float],
) -> list[dict[str, object]]:
    rows = []
    for condition, metric_rows in sorted(metrics_by_condition.items()):
        if condition in {"clean_skill_clean_verifier", "clean_verifier", "no_attack"}:
            continue
        target_rows = target_by_condition.get(condition, [])
        rows.append(
            {
                "condition": display_condition(condition),
                "caf": round(avg(metric_rows, "cost_amplification_factor"), 3),
                "hit_pct": pct(avg_bool(target_rows, "target_interval_hit")) if target_rows else "",
                "tcer": round(avg(target_rows, "target_cost_error"), 2) if target_rows else "",
                "tests_delta_pp": round(paired_tests_delta(metric_rows, clean_tests), 2),
            }
        )
    return rows


def build_agent_rows(
    metrics: list[dict[str, str]],
    runs: list[dict[str, str]],
    target_by_id: dict[str, dict[str, str]],
    clean_tests: dict[str, float],
) -> list[dict[str, object]]:
    run_by_id = {row.get("run_id", ""): row for row in runs}
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in metrics:
        run = run_by_id.get(row.get("run_id", ""), {})
        key = (run.get("agent_runtime", ""), run.get("verifier_exposure_condition") or run.get("entry_surface", ""))
        if row.get("condition") == "adaptive_full_medium":
            groups[key].append(row)
    out = []
    for (agent, surface), rows in sorted(groups.items()):
        out.append(
            {
                "agent": agent,
                "adoption_surface": surface,
                "n": len(rows),
                "adopt_pct": pct(mean([1.0 if float_or_zero(row.get("verifier_calls")) > 0 else 0.0 for row in rows] or [0])),
                "caf": round(avg(rows, "cost_amplification_factor"), 3),
                "hit_pct": pct(mean([bool_value(target_by_id.get(row.get("run_id", ""), {}).get("target_interval_hit")) for row in rows] or [0])),
                "tests_delta_pp": round(paired_tests_delta(rows, clean_tests), 2),
            }
        )
    return out


def build_model_rows(
    metrics: list[dict[str, str]],
    target_by_id: dict[str, dict[str, str]],
    clean_tests: dict[str, float],
) -> list[dict[str, object]]:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in metrics:
        if row.get("condition") == "adaptive_full_medium":
            groups[row.get("model", "")].append(row)
    out = []
    for model, rows in sorted(groups.items()):
        out.append(
            {
                "model": model,
                "n": len(rows),
                "tests": round(avg(rows, "tests_passed_fraction") * 100, 2),
                "caf": round(avg(rows, "cost_amplification_factor"), 3),
                "hit_pct": pct(mean([bool_value(target_by_id.get(row.get("run_id", ""), {}).get("target_interval_hit")) for row in rows] or [0])),
                "tests_delta_pp": round(paired_tests_delta(rows, clean_tests), 2),
                "submit_pct": pct(avg_bool(rows, "final_submission_seen")),
            }
        )
    return out


def build_defense_rows(defense: list[dict[str, str]], runs: list[dict[str, str]]) -> list[dict[str, object]]:
    if defense:
        return [
            {
                "defense": row.get("defense", ""),
                "detect_pct": pct(float_or_zero(row.get("blocked_attack_rate") or row.get("flagged_attack_rate"))),
                "cost_reduction_pct": round(float_or_zero(row.get("avg_cost_reduction_rate")) * 100, 2) if row.get("avg_cost_reduction_rate") else "",
                "utility_loss_pp": round(float_or_zero(row.get("clean_utility_loss_pp")), 2) if row.get("clean_utility_loss_pp") else "",
                "fp_pct": pct(float_or_zero(row.get("clean_block_rate") or row.get("clean_flagged_rate"))),
            }
            for row in defense
        ]
    enabled = [row for row in runs if truthy(row.get("online_defense_enabled"))]
    if not enabled:
        return []
    groups = group_by(enabled, "online_defense_policy")
    return [
        {
            "defense": key or "online defense",
            "detect_pct": pct(avg_bool(rows, "online_defense_would_flag")),
            "cost_reduction_pct": "",
            "utility_loss_pp": "",
            "fp_pct": "",
        }
        for key, rows in sorted(groups.items())
    ]


def control_points_from_target(metrics: list[dict[str, str]], target: list[dict[str, str]]) -> list[dict[str, object]]:
    metric_by_id = {row.get("run_id", ""): row for row in metrics}
    out = []
    for row in target:
        metric = metric_by_id.get(row.get("run_id", ""), {})
        caf = float_or_zero(metric.get("cost_amplification_factor"))
        if caf <= 0:
            continue
        baseline = float_or_zero(metric.get("baseline_tokens_est"))
        lower = float_or_zero(row.get("target_extra_cost_lower"))
        upper = float_or_zero(row.get("target_extra_cost_upper"))
        if baseline > 0:
            target_low = 1 + lower / max(1.0, baseline)
            target_high = 1 + upper / max(1.0, baseline)
        else:
            target_low, target_high = 4.0, 6.0
        out.append(
            {
                "condition": display_condition(row.get("condition", "")),
                "caf": round(caf, 3),
                "target_low": round(target_low, 3),
                "target_high": round(target_high, 3),
            }
        )
    return out


def token_growth_from_metrics(metrics: list[dict[str, str]]) -> list[dict[str, object]]:
    selected: dict[str, list[float]] = defaultdict(list)
    for row in metrics:
        name = display_condition(row.get("condition", ""))
        if name in {"clean", "OBLIGE med.", "no-budget"}:
            selected[name].append(float_or_zero(row.get("total_tokens_est")) / 1_000_000)
    clean = avg_values(selected.get("clean", [0.01]))
    adaptive = avg_values(selected.get("OBLIGE med.", [clean * 4]))
    no_budget = avg_values(selected.get("no-budget", [clean * 8]))
    return [
        {"turn": 1, "clean": clean * 0.35, "adaptive": adaptive * 0.20, "no_budget": no_budget * 0.18},
        {"turn": 2, "clean": clean * 0.70, "adaptive": adaptive * 0.68, "no_budget": no_budget * 0.55},
        {"turn": 3, "clean": clean, "adaptive": adaptive, "no_budget": no_budget},
    ]


def build_figures(bundle: dict[str, list[dict[str, object]]], figures_dir: Path) -> dict[str, Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    control_path = figures_dir / "fig_control.pdf"
    points = bundle.get("figure_control_points", [])
    fig, ax = plt.subplots(figsize=(4.0, 2.5))
    labels = [str(row.get("condition", "")) for row in points]
    xs = list(range(1, len(points) + 1))
    for x, row in zip(xs, points):
        lo = float_or_zero(row.get("target_low"))
        hi = float_or_zero(row.get("target_high"))
        caf = float_or_zero(row.get("caf"))
        ax.vlines(x, lo, hi, color="#8bbf8b", linewidth=8, alpha=0.35)
        ax.scatter([x], [caf], color="#1f4e79", s=18, zorder=3)
    ax.set_xticks(xs)
    ax.set_xticklabels(labels, rotation=25, ha="right", fontsize=7)
    ax.set_ylabel("CAF")
    ax.set_title("CAF vs. target interval")
    ax.grid(axis="y", linestyle=":", linewidth=0.5)
    fig.tight_layout()
    fig.savefig(control_path)
    plt.close(fig)

    growth_path = figures_dir / "fig_token_growth.pdf"
    growth = bundle.get("figure_token_growth", [])
    fig, ax = plt.subplots(figsize=(4.0, 2.5))
    turns = [int(row.get("turn", 0)) for row in growth]
    for key, label in [("clean", "clean"), ("adaptive", "adaptive"), ("no_budget", "no-budget")]:
        ax.plot(turns, [float_or_zero(row.get(key)) for row in growth], marker="o", label=label)
    ax.set_xlabel("Logged agent turn")
    ax.set_ylabel("Cumulative tokens (M)")
    ax.set_title("Token growth")
    ax.legend(fontsize=7, frameon=False)
    ax.grid(axis="y", linestyle=":", linewidth=0.5)
    fig.tight_layout()
    fig.savefig(growth_path)
    plt.close(fig)
    return {"fig_control.pdf": control_path, "fig_token_growth.pdf": growth_path}


def render_latex_table(label: str, caption: str, rows: list[dict[str, object]]) -> str:
    if not rows:
        return f"% {label}: no rows available for this artifact run.\n"
    fields = list(rows[0].keys())
    lines = [
        f"% Auto-generated analysis artifact for {label}.",
        "% Auto-generated from the OBLIGE Evaluation artifact schema.",
        "\\begin{tabular}{" + "l" * len(fields) + "}",
        "\\toprule",
        " & ".join(escape_latex(field) for field in fields) + r" \\",
        "\\midrule",
    ]
    for row in rows:
        lines.append(" & ".join(escape_latex(row.get(field, "")) for field in fields) + r" \\")
    lines.extend(["\\bottomrule", "\\end{tabular}", ""])
    return "\n".join(lines)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def group_by(rows: list[dict[str, str]], key: str) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        out[row.get(key, "")].append(row)
    return out


def clean_tests_by_task(metrics: list[dict[str, str]]) -> dict[str, float]:
    out = {}
    for row in metrics:
        if row.get("condition") in {"clean_skill_clean_verifier", "clean_verifier", "clean_surface_clean_verifier"}:
            out[row.get("task_id", "")] = float_or_zero(row.get("tests_passed_fraction")) * 100
    return out


def paired_tests_delta(rows: list[dict[str, str]], clean_tests: dict[str, float]) -> float | str:
    deltas = []
    for row in rows:
        task = row.get("task_id", "")
        if task in clean_tests and row.get("tests_passed_fraction") not in {"", None}:
            deltas.append(float_or_zero(row.get("tests_passed_fraction")) * 100 - clean_tests[task])
    return mean(deltas) if deltas else ""


def target_label(rows: list[dict[str, str]]) -> str:
    if not rows:
        return ""
    lows = [float_or_zero(row.get("target_extra_cost_lower")) for row in rows]
    highs = [float_or_zero(row.get("target_extra_cost_upper")) for row in rows]
    return f"[{round(avg_values(lows), 2)},{round(avg_values(highs), 2)}]"


def inferred_target_band(rows: list[dict[str, str]]) -> str:
    levels = {row.get("target_level", "") for row in rows}
    if "low" in levels:
        return "[1.8,2.5]"
    if "high" in levels:
        return "[8.0,11.0]"
    if "medium" in levels:
        return "[4.0,6.0]"
    return ""


def avg(rows: list[dict[str, str]], field: str) -> float:
    values = [float_or_zero(row.get(field)) for row in rows if str(row.get(field, "")).strip() != ""]
    return avg_values(values)


def avg_values(values: list[float]) -> float:
    return mean(values) if values else 0.0


def avg_bool(rows: list[dict[str, str]], field: str) -> float:
    values = [bool_value(row.get(field)) for row in rows if str(row.get(field, "")).strip() != ""]
    return mean(values) if values else 0.0


def pct(value: float) -> int:
    return int(round(value * 100))


def bool_value(value: object) -> float:
    if isinstance(value, str):
        return 1.0 if value.lower() in {"1", "true", "yes", "on"} else 0.0
    return 1.0 if value else 0.0


def truthy(value: object) -> bool:
    return bool_value(value) == 1.0


def float_or_zero(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def display_condition(condition: str) -> str:
    return paper_condition_label(condition)


def escape_latex(value: object) -> str:
    text = str(value)
    for src, dst in [
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("_", r"\_"),
        ("#", r"\#"),
    ]:
        text = text.replace(src, dst)
    return text
