from __future__ import annotations

import argparse

from edos.analysis.defense_eval import (
    DefenseEvalConfig,
    build_defense_evidence_bundle,
    load_defense_eval_config,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Defaults to <run-dir>/aggregate/defense_evidence.",
    )
    parser.add_argument(
        "--refresh-aggregate",
        action="store_true",
        help="Regenerate aggregate CSV files before building defense evidence.",
    )
    parser.add_argument(
        "--defense-config",
        default=None,
        help="Optional JSON config. Explicit CLI thresholds override config values.",
    )
    parser.add_argument("--max-verifier-calls", type=int, default=None)
    parser.add_argument("--max-total-tokens", type=int, default=None)
    parser.add_argument("--max-wall-clock-seconds", type=float, default=None)
    parser.add_argument("--max-controller-extra-cost", type=float, default=None)
    parser.add_argument("--budget-monitor-threshold", type=float, default=None)
    parser.add_argument("--resource-abuse-classifier-threshold", type=float, default=None)
    parser.add_argument("--llm-judge-threshold", type=float, default=None)
    parser.add_argument("--classifier-records-path", default=None)
    parser.add_argument("--llm-judge-records-path", default=None)
    parser.add_argument(
        "--allowed-entry-surface",
        action="append",
        default=None,
        help="Allowed tool surface for tool_allowlist. Pass multiple times.",
    )
    args = parser.parse_args()

    base_config = (
        load_defense_eval_config(args.defense_config)
        if args.defense_config
        else DefenseEvalConfig()
    )
    config = DefenseEvalConfig(
        max_verifier_calls=pick(args.max_verifier_calls, base_config.max_verifier_calls),
        max_total_tokens=pick(args.max_total_tokens, base_config.max_total_tokens),
        max_wall_clock_seconds=pick(
            args.max_wall_clock_seconds,
            base_config.max_wall_clock_seconds,
        ),
        max_controller_extra_cost=pick(
            args.max_controller_extra_cost,
            base_config.max_controller_extra_cost,
        ),
        budget_monitor_threshold=pick(
            args.budget_monitor_threshold,
            base_config.budget_monitor_threshold,
        ),
        resource_abuse_classifier_threshold=pick(
            args.resource_abuse_classifier_threshold,
            base_config.resource_abuse_classifier_threshold,
        ),
        llm_judge_threshold=pick(
            args.llm_judge_threshold,
            base_config.llm_judge_threshold,
        ),
        classifier_records_path=pick(
            args.classifier_records_path,
            base_config.classifier_records_path,
        ),
        llm_judge_records_path=pick(
            args.llm_judge_records_path,
            base_config.llm_judge_records_path,
        ),
        allowed_entry_surfaces=(
            frozenset(args.allowed_entry_surface)
            if args.allowed_entry_surface is not None
            else base_config.allowed_entry_surfaces
        ),
    )
    paths = build_defense_evidence_bundle(
        args.run_dir,
        output_dir=args.output_dir,
        refresh_aggregate=args.refresh_aggregate,
        config=config,
    )
    for name, path in paths.items():
        print(f"{name}: {path}")


def pick(override, default):
    return override if override is not None else default


if __name__ == "__main__":
    main()
