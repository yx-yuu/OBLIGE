#!/usr/bin/env bash
set -euo pipefail

if ! command -v opencode >/dev/null 2>&1; then
  echo "opencode is not installed or not on PATH." >&2
  echo "Install it first, for example: npm install -g opencode-ai" >&2
  exit 127
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="configs/experiments/opencode_real_programbench_mechanism_cleanroom_pilot30.json"
SPLIT="configs/task_splits/programbench_pilot_30.json"
RUN_DIR="runs/opencode_real_programbench_mechanism_cleanroom_pilot30"
DOCKER_ARGS=()
if [ -n "${EDOS_DOCKER_HOST:-}" ]; then
  DOCKER_ARGS=(--docker-host "${EDOS_DOCKER_HOST}")
fi

export XDG_DATA_HOME="${ROOT_DIR}/temp/opencode-real-programbench-mechanism-cleanroom-pilot30/data"
export XDG_CONFIG_HOME="${ROOT_DIR}/temp/opencode-real-programbench-mechanism-cleanroom-pilot30/config"
export XDG_STATE_HOME="${ROOT_DIR}/temp/opencode-real-programbench-mechanism-cleanroom-pilot30/state"
mkdir -p "$XDG_DATA_HOME" "$XDG_CONFIG_HOME" "$XDG_STATE_HOME"

cd "$ROOT_DIR"

PYTHONPATH=src python -m edos.cli.build_programbench_split \
  --programbench-root temp/external_repos/ProgramBench \
  --output "$SPLIT" \
  --limit 30 \
  --seed 20260524 \
  --difficulty easy \
  --difficulty medium \
  --difficulty hard \
  --exclude-repository-prefix testorg/ \
  --per-difficulty-limit 10 \
  --per-category-limit 6

PYTHONPATH=src python -m edos.cli.audit_task_materials \
  --config "$CONFIG" \
  --output "${RUN_DIR}/task_material_audit.preflight.json" \
  --require-status programbench_cleanroom_workspace

PYTHONPATH=src python -m edos.cli.docker_preflight \
  --config "$CONFIG" \
  --output "${RUN_DIR}/docker_preflight.json" \
  "${DOCKER_ARGS[@]}"

PYTHONPATH=src python -m edos.cli.run_experiment \
  --config "$CONFIG" \
  --require-task-material-status programbench_cleanroom_workspace

PYTHONPATH=src python -m edos.cli.aggregate_results --run-dir "$RUN_DIR"
