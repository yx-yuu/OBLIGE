from __future__ import annotations

import argparse

from edos.programbench.mini_results import ingest_mini_sweagent_results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="mini-SWE-agent ProgramBench output directory")
    parser.add_argument("--run-dir", required=True, help="Target EDoS harness run directory")
    parser.add_argument("--experiment-name", default="mini_sweagent_programbench")
    parser.add_argument("--condition", default="no_attack")
    parser.add_argument("--target-level", default="none")
    parser.add_argument("--verifier-exposure-condition", default="no_mention")
    parser.add_argument("--entry-surface", default="")
    parser.add_argument("--surface-artifact", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--model-version", default="")
    parser.add_argument("--agent-version", default="mini-swe-agent")
    parser.add_argument("--task-list", default="")
    args = parser.parse_args()

    summary = ingest_mini_sweagent_results(
        source=args.source,
        run_dir=args.run_dir,
        experiment_name=args.experiment_name,
        condition=args.condition,
        target_level=args.target_level,
        verifier_exposure_condition=args.verifier_exposure_condition,
        entry_surface=args.entry_surface,
        surface_artifact=args.surface_artifact,
        model=args.model,
        model_version=args.model_version,
        agent_version=args.agent_version,
        task_list=args.task_list or None,
    )
    print(
        "Imported {imported} mini-SWE-agent run(s); "
        "missing_submission={missing_submission}; "
        "missing_trajectory={missing_trajectory}".format(**summary)
    )


if __name__ == "__main__":
    main()
