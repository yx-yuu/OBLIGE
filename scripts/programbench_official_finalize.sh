#!/usr/bin/env bash
set -euo pipefail

if (( $# >= 1 )); then
  RUN_DIR="$1"
  shift
else
  RUN_DIR="runs/programbench_export_smoke"
fi

if (( $# >= 1 )); then
  PROGRAMBENCH_ROOT="$1"
  shift
else
  PROGRAMBENCH_ROOT="temp/external_repos/ProgramBench"
fi

DOCKER_ARGS=()
if [ -n "${EDOS_DOCKER_HOST:-}" ]; then
  DOCKER_ARGS=(--docker-host "${EDOS_DOCKER_HOST}")
fi

PYTHONPATH=src python -m edos.cli.finalize_programbench_scores \
  --run-dir "$RUN_DIR" \
  --programbench-root "$PROGRAMBENCH_ROOT" \
  "${DOCKER_ARGS[@]}" \
  "$@"
