#!/usr/bin/env bash
set -euo pipefail

PYTHONPATH=src python -m edos.cli.run_experiment --config configs/experiments/local_command_smoke.json
PYTHONPATH=src python -m edos.cli.aggregate_results --run-dir runs/local_command_smoke

