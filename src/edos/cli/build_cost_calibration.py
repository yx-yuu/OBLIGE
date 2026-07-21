from __future__ import annotations

import argparse

from edos.analysis.cost_calibration import build_cost_calibration_bundle


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Defaults to <run-dir>/aggregate/cost_calibration.",
    )
    parser.add_argument(
        "--refresh-aggregate",
        action="store_true",
        help="Regenerate aggregate CSV files before building cost calibration evidence.",
    )
    args = parser.parse_args()
    paths = build_cost_calibration_bundle(
        args.run_dir,
        output_dir=args.output_dir,
        refresh_aggregate=args.refresh_aggregate,
    )
    for name, path in paths.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
