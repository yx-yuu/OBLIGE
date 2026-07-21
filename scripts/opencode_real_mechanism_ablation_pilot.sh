#!/usr/bin/env bash
set -euo pipefail

if ! command -v opencode >/dev/null 2>&1; then
  echo "opencode is not installed or not on PATH." >&2
  echo "Install it first, for example: npm install -g opencode-ai" >&2
  exit 127
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export XDG_DATA_HOME="${ROOT_DIR}/temp/opencode-real-mechanism-ablation/data"
export XDG_CONFIG_HOME="${ROOT_DIR}/temp/opencode-real-mechanism-ablation/config"
export XDG_STATE_HOME="${ROOT_DIR}/temp/opencode-real-mechanism-ablation/state"
mkdir -p "$XDG_DATA_HOME" "$XDG_CONFIG_HOME" "$XDG_STATE_HOME"

PYTHONPATH=src python -m edos.cli.run_experiment --config configs/experiments/opencode_real_mechanism_ablation_pilot.json
PYTHONPATH=src python -m edos.cli.aggregate_results --run-dir runs/opencode_real_mechanism_ablation_pilot
