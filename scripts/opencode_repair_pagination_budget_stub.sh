#!/usr/bin/env bash
set -euo pipefail

PYTHONPATH=src python -m edos.cli.run_experiment --config configs/experiments/opencode_repair_pagination_budget_stub.json
PYTHONPATH=src python -m edos.cli.aggregate_results --run-dir runs/opencode_repair_pagination_budget_stub
