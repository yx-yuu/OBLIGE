from __future__ import annotations

import argparse

from edos.analysis.aggregate import aggregate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    paths = aggregate(args.run_dir)
    for name, path in paths.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()

