from __future__ import annotations

import argparse

from edos.analysis.evaluation_artifacts import build_evaluation_artifacts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["smoke", "aggregate"],
        default="smoke",
        help="smoke builds a deterministic reviewer fixture; aggregate reads observed run artifacts.",
    )
    parser.add_argument(
        "--run-dir",
        default=None,
        help="Experiment run directory required for --mode aggregate.",
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts/evaluation_smoke",
        help="Directory for generated tables, figures, and manifest.",
    )
    parser.add_argument(
        "--refresh-aggregate",
        action="store_true",
        help="Regenerate aggregate CSVs before building aggregate-mode artifacts.",
    )
    args = parser.parse_args()
    paths = build_evaluation_artifacts(
        output_dir=args.output_dir,
        mode=args.mode,
        run_dir=args.run_dir,
        refresh_aggregate=args.refresh_aggregate,
    )
    for name, path in paths.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
