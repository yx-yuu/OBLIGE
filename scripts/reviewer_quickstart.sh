#!/usr/bin/env bash
set -euo pipefail

TASK_LIMIT="${1:-1}"
RUN_DIR="${2:-runs/reviewer_quick_local_${TASK_LIMIT}}"
EVAL_DIR="${3:-artifacts/reviewer_quick_local_${TASK_LIMIT}}"

CONFIG="${EDOS_REVIEWER_CONFIG:-configs/experiments/reviewer_quick_local.json}"
PYTHON_BIN="${PYTHON:-python}"

case "${TASK_LIMIT}" in
  ''|*[!0-9]*)
    echo "TASK_LIMIT must be a non-negative integer." >&2
    exit 2
    ;;
esac

if [ "${TASK_LIMIT}" -gt 20 ]; then
  echo "TASK_LIMIT must be <= 20 for reviewer_quick_local." >&2
  exit 2
fi

export PYTHONPATH="src${PYTHONPATH:+:${PYTHONPATH}}"

echo "[reviewer] running deterministic local experiment: task_limit=${TASK_LIMIT}, run_dir=${RUN_DIR}"
"${PYTHON_BIN}" -m edos.cli.run_experiment \
  --config "${CONFIG}" \
  --task-limit "${TASK_LIMIT}" \
  --output-dir "${RUN_DIR}"

echo "[reviewer] aggregating run artifacts"
"${PYTHON_BIN}" -m edos.cli.aggregate_results \
  --run-dir "${RUN_DIR}"

echo "[reviewer] building Evaluation tables and figures"
"${PYTHON_BIN}" -m edos.cli.build_evaluation_artifacts \
  --mode aggregate \
  --run-dir "${RUN_DIR}" \
  --output-dir "${EVAL_DIR}"

echo "[reviewer] run artifacts: ${RUN_DIR}"
echo "[reviewer] evaluation artifacts: ${EVAL_DIR}"
