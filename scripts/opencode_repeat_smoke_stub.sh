#!/usr/bin/env bash
set -euo pipefail

PYTHONPATH=src python -m edos.cli.run_experiment --config configs/experiments/opencode_repeat_smoke_stub.json
PYTHONPATH=src python -m edos.cli.aggregate_results --run-dir runs/opencode_repeat_smoke_stub
