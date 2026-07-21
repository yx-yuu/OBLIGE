from __future__ import annotations

import argparse
import json

from edos.programbench.mini_verifier import prepare_mini_sweagent_condition


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mini-sweagent-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--condition", required=True)
    parser.add_argument(
        "--verifier-mode",
        default="absent",
        choices=["absent", "clean", "polluted"],
    )
    parser.add_argument(
        "--exposure-condition",
        default="no_mention",
        choices=[
            "no_mention",
            "tool_available",
            "light_prompt",
            "skill_guided",
            "workflow_guided",
            "workflow_enforced",
        ],
    )
    parser.add_argument("--docker-cpus", type=int, default=4)
    parser.add_argument("--memory", default="8g")
    parser.add_argument("--tool-mount-target", default="/edos_tools")
    parser.add_argument("--src-mount-target", default="/edos_src")
    parser.add_argument(
        "--workflow-trigger-once",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="For workflow_enforced conditions, inject the verifier at most once.",
    )
    parser.add_argument(
        "--workflow-trigger-max-calls",
        type=int,
        default=1,
        help="For workflow_enforced conditions, maximum injected verifier calls; 0 means unlimited.",
    )
    parser.add_argument(
        "--workflow-trigger-until-closed",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="For workflow_enforced conditions, stop injected calls after CLOSED/BUDGET_CLOSED.",
    )
    parser.add_argument(
        "--online-defense-enabled",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Expose online-defense runtime variables in the generated condition.",
    )
    parser.add_argument(
        "--online-defense-policy",
        action="append",
        default=[],
        help="Online defense policy. Can be passed multiple times.",
    )
    parser.add_argument(
        "--online-defense-mode",
        choices=["monitor", "enforce"],
        default="",
    )
    parser.add_argument("--online-defense-max-verifier-calls", type=int, default=None)
    parser.add_argument("--online-defense-max-controller-extra-cost", type=float, default=None)
    parser.add_argument("--online-defense-budget-monitor-threshold", type=float, default=None)
    args = parser.parse_args()

    manifest = prepare_mini_sweagent_condition(
        mini_sweagent_root=args.mini_sweagent_root,
        output_dir=args.output_dir,
        condition=args.condition,
        verifier_mode=args.verifier_mode,
        exposure_condition=args.exposure_condition,
        docker_cpus=args.docker_cpus,
        memory=args.memory,
        tool_mount_target=args.tool_mount_target,
        src_mount_target=args.src_mount_target,
        workflow_trigger_once=args.workflow_trigger_once,
        workflow_trigger_max_calls=args.workflow_trigger_max_calls,
        workflow_trigger_until_closed=args.workflow_trigger_until_closed,
        online_defense=build_online_defense_config(args),
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def build_online_defense_config(args: argparse.Namespace) -> dict:
    values: dict[str, object] = {}
    if args.online_defense_enabled is not None:
        values["enabled"] = args.online_defense_enabled
    if args.online_defense_policy:
        values["policies"] = args.online_defense_policy
    if args.online_defense_mode:
        values["mode"] = args.online_defense_mode
    if args.online_defense_max_verifier_calls is not None:
        values["max_verifier_calls"] = args.online_defense_max_verifier_calls
    if args.online_defense_max_controller_extra_cost is not None:
        values["max_controller_extra_cost"] = args.online_defense_max_controller_extra_cost
    if args.online_defense_budget_monitor_threshold is not None:
        values["budget_monitor_threshold"] = args.online_defense_budget_monitor_threshold
    if values and "enabled" not in values:
        values["enabled"] = True
    return values


if __name__ == "__main__":
    main()
