from __future__ import annotations

import argparse
from pathlib import Path

from edos.analysis.external_validity import build_external_validity_bundle


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-dir",
        action="append",
        required=True,
        help="Run directory containing aggregate outputs. Pass multiple times for cross-agent evidence.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Defaults to <first-run-dir>/aggregate/external_validity.",
    )
    parser.add_argument(
        "--refresh-aggregate",
        action="store_true",
        help="Regenerate each run directory's aggregate CSV files before building evidence.",
    )
    args = parser.parse_args()

    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else Path(args.run_dir[0]) / "aggregate" / "external_validity"
    )
    paths = build_external_validity_bundle(
        args.run_dir,
        output_dir=output_dir,
        refresh_aggregate=args.refresh_aggregate,
    )
    for name, path in paths.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
