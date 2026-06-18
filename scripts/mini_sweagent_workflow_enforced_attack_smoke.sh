#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

MODEL_CONFIG="${EDOS_MODEL_CONFIG:-configs/models/openai_compatible.json}"
MINI_ROOT="${EDOS_MINI_SWEAGENT_ROOT:-temp/external_repos/mini-swe-agent}"
PROGRAMBENCH_ROOT="${EDOS_PROGRAMBENCH_ROOT:-temp/external_repos/ProgramBench}"
OUTPUT_ROOT="${EDOS_MINI_OUTPUT_ROOT:-runs/mini_sweagent_workflow_enforced_attack_smoke}"
CONDITIONS_ROOT="${EDOS_MINI_CONDITIONS_ROOT:-${OUTPUT_ROOT}/conditions}"
FILTER="${EDOS_MINI_FILTER:-abishekvashok__cmatrix.*}"
STEP_LIMIT="${EDOS_MINI_STEP_LIMIT:-50}"
WORKERS="${EDOS_MINI_WORKERS:-1}"
EXPERIMENT_NAME="${EDOS_MINI_EXPERIMENT_NAME:-mini_sweagent_workflow_enforced_attack_smoke}"
DRY_RUN="${EDOS_MINI_DRY_RUN:-0}"
EXECUTION_MODE="${EDOS_MINI_EXECUTION_MODE:-local_venv}"

DOCKER_ARGS=()
if [ -n "${EDOS_DOCKER_HOST:-}" ]; then
  DOCKER_ARGS=(--docker-host "${EDOS_DOCKER_HOST}")
fi

mkdir -p "${OUTPUT_ROOT}"

EDOS_MINI_CONDITIONS_ROOT="${CONDITIONS_ROOT}" \
  EDOS_MINI_SWEAGENT_ROOT="${MINI_ROOT}" \
  scripts/prepare_mini_sweagent_conditions.sh

run_mini_condition() {
  local output="$1"
  local condition_config="$2"
  shift 2
  local dry_run_args=()
  if [ "${DRY_RUN}" = "1" ]; then
    dry_run_args=(--dry-run --skip-preflight)
  fi

  PYTHONPATH=src python -m edos.cli.run_mini_sweagent_programbench \
    --mini-sweagent-root "${MINI_ROOT}" \
    --programbench-root "${PROGRAMBENCH_ROOT}" \
    --output "${output}" \
    --model-config "${MODEL_CONFIG}" \
    --filter "${FILTER}" \
    --workers "${WORKERS}" \
    --execution-mode "${EXECUTION_MODE}" \
    --config programbench.yaml \
    --config "${condition_config}" \
    --extra-config "agent.step_limit=${STEP_LIMIT}" \
    "${DOCKER_ARGS[@]}" \
    "${dry_run_args[@]}" \
    "$@"
}

run_mini_condition \
  "${OUTPUT_ROOT}/raw_clean" \
  "${CONDITIONS_ROOT}/clean_workflow_enforced/clean_skill_clean_verifier__workflow_enforced.yaml"

run_mini_condition \
  "${OUTPUT_ROOT}/raw_polluted" \
  "${CONDITIONS_ROOT}/polluted_workflow_enforced/adaptive_full_medium__workflow_enforced.yaml" \
  --skip-preflight

if [ "${DRY_RUN}" = "1" ]; then
  echo "Dry run complete. Set EDOS_MINI_DRY_RUN=0 or unset it to execute mini-SWE-agent."
  exit 0
fi

PYTHONPATH=src python -m edos.cli.ingest_mini_sweagent_results \
  --source "${OUTPUT_ROOT}/raw_clean" \
  --run-dir "${OUTPUT_ROOT}/imported" \
  --experiment-name "${EXPERIMENT_NAME}" \
  --condition clean_skill_clean_verifier \
  --target-level none \
  --verifier-exposure-condition workflow_enforced

PYTHONPATH=src python -m edos.cli.ingest_mini_sweagent_results \
  --source "${OUTPUT_ROOT}/raw_polluted" \
  --run-dir "${OUTPUT_ROOT}/imported" \
  --experiment-name "${EXPERIMENT_NAME}" \
  --condition adaptive_full_medium \
  --target-level medium \
  --verifier-exposure-condition workflow_enforced

PYTHONPATH=src python -m edos.cli.aggregate_results --run-dir "${OUTPUT_ROOT}/imported"
