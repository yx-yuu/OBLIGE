#!/usr/bin/env bash
set -euo pipefail

MODEL="${1:-test/model}"
MODEL_CONFIG="${EDOS_MODEL_CONFIG:-}"

MODEL_ARGS=(--model "${MODEL}")
if [[ -n "${MODEL_CONFIG}" ]]; then
  MODEL_ARGS=(--model-config "${MODEL_CONFIG}")
fi

PYTHONPATH=src python -m edos.cli.run_mini_sweagent_programbench \
  --mini-sweagent-root temp/external_repos/mini-swe-agent \
  --programbench-root temp/external_repos/ProgramBench \
  --output runs/mini_sweagent_programbench_smoke \
  "${MODEL_ARGS[@]}" \
  --filter 'abishekvashok__cmatrix.*' \
  --preflight-only \
  --preflight-report runs/mini_sweagent_programbench_smoke/preflight.json
